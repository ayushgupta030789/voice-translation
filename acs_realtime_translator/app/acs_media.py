import base64
import json
import logging

from app.config import get_settings
from app.models import TranslationCallSession
from app.realtime_translate import RealtimeTranslator

logger = logging.getLogger(__name__)


async def ensure_translation_sessions(session: TranslationCallSession) -> None:
    """Open two directional model sessions after both ACS media sockets exist."""
    if not session.incoming_media_ws or not session.outbound_media_ws:
        return

    async with session.state_lock:
        if session.incoming_to_outbound_translator is None:
            session.incoming_to_outbound_translator = RealtimeTranslator(
                source_language=session.incoming_language,
                target_language=session.outbound_language,
                on_audio=lambda audio: send_audio_to_acs_leg(
                    session, "outbound", audio
                ),
            )
            await session.incoming_to_outbound_translator.connect()

        if session.outbound_to_incoming_translator is None:
            session.outbound_to_incoming_translator = RealtimeTranslator(
                source_language=session.outbound_language,
                target_language=session.incoming_language,
                on_audio=lambda audio: send_audio_to_acs_leg(
                    session, "incoming", audio
                ),
            )
            await session.outbound_to_incoming_translator.connect()


async def route_pcm_audio(
    session: TranslationCallSession,
    source_leg: str,
    pcm_audio: bytes,
) -> None:
    translator = (
        session.incoming_to_outbound_translator
        if source_leg == "incoming"
        else session.outbound_to_incoming_translator
    )
    if translator:
        await translator.send_audio(pcm_audio)


async def handle_acs_media_message(
    session: TranslationCallSession,
    source_leg: str,
    raw_message: str,
) -> None:
    message = json.loads(raw_message)
    kind = message.get("kind")

    if get_settings().log_media_messages:
        logger.debug("ACS media message on %s: %s", source_leg, kind)

    if kind == "AudioData":
        audio_data = message.get("audioData", {})
        encoded_audio = audio_data.get("data")
        if encoded_audio and not audio_data.get("silent", False):
            await route_pcm_audio(
                session,
                source_leg,
                base64.b64decode(encoded_audio),
            )
    elif kind == "AudioMetadata":
        logger.info("ACS audio metadata for %s: %s", source_leg, message)


async def send_audio_to_acs_leg(
    session: TranslationCallSession,
    destination_leg: str,
    pcm_audio: bytes,
) -> None:
    if destination_leg == "incoming":
        websocket = session.incoming_media_ws
        lock = session.incoming_send_lock
    else:
        websocket = session.outbound_media_ws
        lock = session.outbound_send_lock

    if not websocket:
        return

    envelope = {
        "kind": "AudioData",
        "audioData": {
            "data": base64.b64encode(pcm_audio).decode("ascii"),
            "silent": False,
        },
    }
    async with lock:
        await websocket.send_text(json.dumps(envelope))
