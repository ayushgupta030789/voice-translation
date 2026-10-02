import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import quote

import websockets
from app.config import get_settings

logger = logging.getLogger(__name__)
AudioCallback = Callable[[bytes], Awaitable[None]]


class RealtimeTranslator:
    """One directional gpt-realtime-translate WebSocket session."""

    def __init__(
        self,
        source_language: str,
        target_language: str,
        on_audio: AudioCallback,
    ) -> None:
        self.source_language = source_language
        self.target_language = target_language
        self.on_audio = on_audio
        self.ws = None
        self.receive_task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()
        self.closed = False

    async def connect(self) -> None:
        settings = get_settings()
        endpoint = settings.azure_openai_endpoint.rstrip("/")
        endpoint = endpoint.replace("https://", "wss://", 1)
        deployment = quote(settings.azure_openai_realtime_deployment, safe="")
        api_version = quote(settings.realtime_api_version, safe="")

        # Some deployments use /openai/v1/realtime?model=..., while older Azure
        # previews use /openai/realtime?api-version=...&deployment=.... Adjust this
        # URL in one place if your deployed API version requires the other form.
        url = (
            f"{endpoint}/openai/realtime"
            f"?api-version={api_version}&deployment={deployment}"
        )

        self.ws = await websockets.connect(
            url,
            additional_headers={"api-key": settings.azure_openai_api_key},
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        )
        await self._configure_session()
        self.receive_task = asyncio.create_task(self._receive_loop())
        logger.info(
            "Realtime translator connected: %s -> %s",
            self.source_language,
            self.target_language,
        )

    async def _configure_session(self) -> None:
        # Translation-model session fields can evolve by API version. Keep the
        # model-specific envelope isolated in this function.
        event = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "source_language": self.source_language,
                "target_language": self.target_language,
            },
        }
        await self.ws.send(json.dumps(event))

    async def send_audio(self, pcm_audio: bytes) -> None:
        if not self.ws or self.closed:
            return
        event = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm_audio).decode("ascii"),
        }
        async with self.send_lock:
            await self.ws.send(json.dumps(event))

    async def _receive_loop(self) -> None:
        try:
            async for raw_message in self.ws:
                event = json.loads(raw_message)
                event_type = event.get("type", "")

                if event_type in {
                    "response.audio.delta",
                    "response.output_audio.delta",
                    "response.output_audio.delta",
                }:
                    delta = event.get("delta")
                    if delta:
                        await self.on_audio(base64.b64decode(delta))
                elif event_type == "error":
                    logger.error("Realtime model error: %s", event)
                elif event_type.endswith("transcript.delta"):
                    logger.debug("Translation transcript: %s", event.get("delta", ""))
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                logger.exception("Realtime receive loop failed")

    async def close(self) -> None:
        self.closed = True
        current = asyncio.current_task()
        if self.receive_task and self.receive_task is not current:
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
