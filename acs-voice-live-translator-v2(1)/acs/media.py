import base64
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def receive_acs_audio(websocket: WebSocket):
    """
    Yields raw PCM audio bytes from ACS Media Streaming.

    ACS sends JSON messages. AudioData contains base64 encoded PCM.
    AudioMetadata is handled/logged separately.
    """
    while True:
        message = await websocket.receive_text()
        event = json.loads(message)
        kind = event.get("kind")

        if kind == "AudioMetadata":
            logger.info("ACS AudioMetadata: %s", event)
            continue

        if kind == "AudioData":
            audio = event.get("audioData", {})
            data = audio.get("data")
            if data:
                yield base64.b64decode(data)
            continue

        if kind == "StopAudio":
            logger.info("ACS StopAudio received")
            return

        logger.debug("Unknown ACS media message: %s", event)


async def send_acs_audio(websocket: WebSocket, pcm: bytes):
    """
    Sends raw PCM16 24-kHz mono audio back to ACS.
    """
    await websocket.send_text(json.dumps({
        "kind": "Media",
        "audioData": {
            "data": base64.b64encode(pcm).decode("ascii")
        }
    }))
