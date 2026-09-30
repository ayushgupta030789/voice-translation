"""Client for the dedicated gpt-realtime-translate WebSocket endpoint.

The documented translation sample consumes translated text events. This module
therefore emits completed translated text segments; Azure Speech TTS converts
those segments to PCM audio before they are sent to the opposite ACS call leg.
"""
import asyncio
import json
import logging
from typing import Optional

import websockets

from config import AZURE_OPENAI_API_KEY, translation_ws_url

logger = logging.getLogger(__name__)


class RealtimeTranslationSession:
    def __init__(self, target_language: str, name: str):
        self.target_language = target_language
        self.name = name
        self.ws = None
        self.receiver_task: Optional[asyncio.Task] = None
        self.translated_text: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self.started = False
        self.closed = False

    async def start(self) -> None:
        if self.started:
            return
        headers = {"api-key": AZURE_OPENAI_API_KEY}
        self.ws = await websockets.connect(
            translation_ws_url(),
            additional_headers=headers,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        )

        # Wait for session.created before updating the session.
        first = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
        if first.get("type") != "session.created":
            raise RuntimeError(f"{self.name}: expected session.created, received {first}")

        await self.ws.send(json.dumps({
            "type": "session.update",
            "session": {"audio": {"output": {"language": self.target_language}}},
        }))

        # Confirm configuration before media starts flowing.
        while True:
            event = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
            event_type = event.get("type")
            if event_type == "session.updated":
                break
            if event_type == "error":
                raise RuntimeError(f"{self.name}: session configuration failed: {event}")
            logger.debug("%s startup event: %s", self.name, event_type)

        self.started = True
        self.receiver_task = asyncio.create_task(self._receive_loop(), name=f"translate-recv-{self.name}")
        logger.info("Translation session ready name=%s target=%s", self.name, self.target_language)

    async def append_audio(self, pcm16: bytes) -> None:
        if not pcm16 or not self.started or self.closed:
            return
        await self.ws.send(json.dumps({
            "type": "session.input_audio_buffer.append",
            "audio": __import__("base64").b64encode(pcm16).decode("ascii"),
        }))

    async def _receive_loop(self) -> None:
        try:
            async for raw in self.ws:
                event = json.loads(raw)
                event_type = event.get("type")
                if event_type == "response.text.delta":
                    # The translation endpoint emits text fragments. Accumulate
                    # them until response.text.done to avoid synthesizing every token.
                    continue
                if event_type == "response.text.done":
                    text = event.get("text", "").strip()
                    if text:
                        logger.info("[%s] translated text: %s", self.name, text)
                        if self.translated_text.full():
                            try:
                                self.translated_text.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        await self.translated_text.put(text)
                elif event_type == "error":
                    logger.error("Translation endpoint error name=%s event=%s", self.name, event)
                elif event_type == "session.closed":
                    logger.info("Translation session closed name=%s", self.name)
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                logger.exception("Translation receive loop failed name=%s", self.name)

    async def get_translated_text(self) -> str:
        return await self.translated_text.get()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.receiver_task:
            self.receiver_task.cancel()
            await asyncio.gather(self.receiver_task, return_exceptions=True)
