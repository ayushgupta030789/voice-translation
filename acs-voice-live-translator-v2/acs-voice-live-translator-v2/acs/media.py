import asyncio
import base64
import json
import logging

from quart import websocket

logger = logging.getLogger(__name__)


async def send_pcm_to_acs(acs_ws, pcm16: bytes) -> None:
    """Send raw PCM16 audio to ACS using its bidirectional media protocol.

    ACS expects raw PCM data encoded as base64 in an AudioData JSON message.
    Split long synthesis results into short frames to avoid large bursts.
    """
    if not acs_ws or not pcm16:
        return
    # 100 ms at 24 kHz, mono, 16-bit = 4,800 bytes.
    frame_bytes = 4800
    for offset in range(0, len(pcm16), frame_bytes):
        frame = pcm16[offset:offset + frame_bytes]
        await acs_ws.send(json.dumps({
            "kind": "AudioData",
            "audioData": {"data": base64.b64encode(frame).decode("ascii")},
        }))
        # Pace frames to their real-time duration instead of flooding ACS.
        await asyncio.sleep(len(frame) / 48000.0)


async def receive_acs_media(session, side: str) -> None:
    ws = websocket._get_current_object()
    session.set_websocket(side, ws)
    logger.info("ACS media WebSocket connected session=%s side=%s", session.session_id, side)

    try:
        # Start translation only once both media WebSockets have connected.
        await session.ensure_translations_started()
        while True:
            raw = await websocket.receive()
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            packet = json.loads(raw)
            kind = packet.get("kind")
            if kind == "AudioMetadata":
                metadata = packet.get("audioMetadata", {})
                logger.info("ACS AudioMetadata session=%s side=%s metadata=%s", session.session_id, side, metadata)
                sample_rate = metadata.get("sampleRate")
                if sample_rate and sample_rate != 24000:
                    logger.warning("Expected 24000 Hz PCM but ACS reports %s Hz; configure PCM24KMono", sample_rate)
            elif kind == "AudioData":
                data = packet.get("audioData", {}).get("data")
                if data:
                    pcm = base64.b64decode(data)
                    queue = session.audio_queue_for_side(side)
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except Exception:
                            pass
                    await queue.put(pcm)
            elif kind == "DtmfData":
                logger.info("ACS DTMF session=%s side=%s data=%s", session.session_id, side, packet.get("dtmfData"))
            else:
                logger.debug("ACS media packet session=%s side=%s kind=%s", session.session_id, side, kind)
    except Exception:
        logger.exception("ACS media WebSocket error session=%s side=%s", session.session_id, side)
    finally:
        logger.info("ACS media WebSocket disconnected session=%s side=%s", session.session_id, side)
        if side == "a" and session.ws_a is ws:
            session.ws_a = None
        elif side == "b" and session.ws_b is ws:
            session.ws_b = None
