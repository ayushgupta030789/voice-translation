import asyncio
import base64
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets

from config import settings

logger = logging.getLogger(__name__)


class RealtimeTranslator:
    """
    One gpt-realtime-translate session.

    Input:
        raw PCM16 mono 24 kHz

    Output:
        translated raw PCM16 mono 24 kHz

    The dedicated translation endpoint is:
        /openai/v1/realtime/translations?model=<deployment>
    """

    def __init__(
        self,
        name: str,
        target_language: str,
        on_audio: Callable[[bytes], Awaitable[None]],
        on_text: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.name = name
        self.target_language = target_language
        self.on_audio = on_audio
        self.on_text = on_text

        self.ws = None
        self._receiver_task = None
        self._closed = False

    def url(self) -> str:
        endpoint = settings.azure_openai_endpoint.rstrip("/")
        if endpoint.startswith("https://"):
            endpoint = "wss://" + endpoint[len("https://"):]
        elif endpoint.startswith("http://"):
            endpoint = "ws://" + endpoint[len("http://"):]

        return (
            f"{endpoint}/openai/v1/realtime/translations"
            f"?model={settings.azure_openai_deployment_name}"
        )

    def headers(self):
        if settings.use_entra_id:
            raise NotImplementedError(
                "USE_ENTRA_ID is reserved for the Entra implementation. "
                "Use AZURE_OPENAI_API_KEY for this starter project."
            )

        return {"api-key": settings.azure_openai_api_key}

    async def connect(self):
        if not settings.azure_openai_endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
        if not settings.azure_openai_api_key and not settings.use_entra_id:
            raise RuntimeError("AZURE_OPENAI_API_KEY is not configured")

        logger.info(
            "[%s] Connecting to gpt-realtime-translate target=%s",
            self.name,
            self.target_language,
        )

        self.ws = await websockets.connect(
            self.url(),
            additional_headers=self.headers(),
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        )

        # Current GA translation session configuration.
        await self.ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "audio": {
                    "input": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": 24000,
                        }
                    },
                    "output": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": 24000,
                        },
                        "language": self.target_language,
                    },
                }
            }
        }))

        # Wait until the model confirms the session is configured.
        while True:
            raw = await self.ws.recv()
            event = json.loads(raw)
            event_type = event.get("type")

            logger.debug("[%s] event=%s", self.name, event_type)

            if event_type == "session.updated":
                logger.info("[%s] Translation session configured", self.name)
                break

            if event_type == "error":
                raise RuntimeError(
                    f"Realtime translation session error: {event}"
                )

        self._receiver_task = asyncio.create_task(self._receiver())

    async def send_audio(self, pcm: bytes):
        if not self.ws or self._closed:
            return

        # Realtime API audio input is base64 encoded in JSON.
        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        }))

    async def _receiver(self):
        try:
            async for raw in self.ws:
                event = json.loads(raw)
                event_type = event.get("type")

                if event_type == "response.output_audio.delta":
                    delta = event.get("delta")
                    if delta:
                        await self.on_audio(base64.b64decode(delta))

                elif event_type == "response.text.delta":
                    text = event.get("text", "")
                    if text and self.on_text:
                        await self.on_text(text)

                elif event_type == "response.text.done":
                    logger.debug("[%s] Translation text completed", self.name)

                elif event_type == "response.done":
                    logger.debug("[%s] Translation response completed", self.name)

                elif event_type == "error":
                    logger.error("[%s] Realtime error: %s", self.name, event)

                elif event_type in {
                    "session.created",
                    "session.updated",
                }:
                    logger.debug("[%s] %s", self.name, event_type)

                else:
                    logger.debug("[%s] event=%s", self.name, event_type)

        except asyncio.CancelledError:
            pass
        except Exception:
            if not self._closed:
                logger.exception("[%s] Translation receiver stopped", self.name)

    async def close(self):
        self._closed = True

        if self._receiver_task:
            self._receiver_task.cancel()
            await asyncio.gather(self._receiver_task, return_exceptions=True)

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
