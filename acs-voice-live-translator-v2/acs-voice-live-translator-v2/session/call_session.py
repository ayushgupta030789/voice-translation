import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import LANGUAGE_A, LANGUAGE_B
from realtime.translator import RealtimeTranslationSession

logger = logging.getLogger(__name__)


@dataclass
class CallSession:
    session_id: str
    incoming_call_id: Optional[str] = None
    outbound_call_id: Optional[str] = None
    ws_a: object | None = None
    ws_b: object | None = None
    audio_a: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    audio_b: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=100))
    translation_a_to_b: RealtimeTranslationSession = field(
        default_factory=lambda: RealtimeTranslationSession(LANGUAGE_B, "A-to-B")
    )
    translation_b_to_a: RealtimeTranslationSession = field(
        default_factory=lambda: RealtimeTranslationSession(LANGUAGE_A, "B-to-A")
    )
    tasks: set[asyncio.Task] = field(default_factory=set)
    startup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    translations_started: bool = False
    closed: bool = False

    def websocket_for_side(self, side: str):
        return self.ws_a if side == "a" else self.ws_b

    def set_websocket(self, side: str, ws) -> None:
        if side == "a":
            self.ws_a = ws
        else:
            self.ws_b = ws

    def audio_queue_for_side(self, side: str) -> asyncio.Queue[bytes]:
        return self.audio_a if side == "a" else self.audio_b

    def translation_for_side(self, side: str):
        return self.translation_a_to_b if side == "a" else self.translation_b_to_a

    async def ensure_translations_started(self) -> None:
        async with self.startup_lock:
            if self.translations_started or self.closed:
                return
            if self.ws_a is None or self.ws_b is None:
                return
            # Start only after both ACS media WebSockets have connected.
            await asyncio.gather(self.translation_a_to_b.start(), self.translation_b_to_a.start())
            self.translations_started = True
            self.add_task(asyncio.create_task(self._audio_pump("a"), name=f"audio-a-{self.session_id}"))
            self.add_task(asyncio.create_task(self._audio_pump("b"), name=f"audio-b-{self.session_id}"))
            self.add_task(asyncio.create_task(self._text_to_speech_pump("a"), name=f"tts-a-{self.session_id}"))
            self.add_task(asyncio.create_task(self._text_to_speech_pump("b"), name=f"tts-b-{self.session_id}"))
            logger.info("Both media legs connected; translation started session=%s", self.session_id)

    async def _audio_pump(self, source_side: str) -> None:
        queue = self.audio_queue_for_side(source_side)
        translator = self.translation_for_side(source_side)
        while not self.closed:
            pcm = await queue.get()
            await translator.append_audio(pcm)

    async def _text_to_speech_pump(self, source_side: str) -> None:
        from realtime.speech_synthesizer import synthesize_translated_text
        from acs.media import send_pcm_to_acs

        translator = self.translation_for_side(source_side)
        destination_side = "b" if source_side == "a" else "a"
        while not self.closed:
            translated_text = await translator.get_translated_text()
            pcm = await synthesize_translated_text(translated_text, destination_side)
            destination_ws = self.websocket_for_side(destination_side)
            if destination_ws and pcm:
                await send_pcm_to_acs(destination_ws, pcm)

    def add_task(self, task: asyncio.Task) -> None:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.gather(
            self.translation_a_to_b.close(),
            self.translation_b_to_a.close(),
            return_exceptions=True,
        )
        self.ws_a = None
        self.ws_b = None
