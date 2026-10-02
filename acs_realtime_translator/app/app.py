import asyncio
import logging
import uuid

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.acs_manager import acs_manager
from app.acs_media import ensure_translation_sessions, handle_acs_media_message, route_pcm_audio
from app.config import get_settings
from app.models import TranslationCallSession
from app.session_manager import session_manager

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
app = FastAPI(title="ACS GPT Realtime Translation Bridge", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/incoming-call")
async def incoming_call(request: Request):
    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    for event in events:
        event_type = event.get("eventType") or event.get("type", "")
        data = event.get("data", {})

        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return JSONResponse(
                content={"validationResponse": data["validationCode"]}
            )

        if event_type != "Microsoft.Communication.IncomingCall":
            continue

        session_id = str(uuid.uuid4())
        session = TranslationCallSession(
            session_id=session_id,
            incoming_language=settings.default_incoming_language,
            outbound_language=settings.default_outbound_language,
            outbound_phone_number=settings.outbound_phone_number,
        )
        await session_manager.create(session)

        try:
            result = await asyncio.to_thread(
                acs_manager.answer_incoming_call,
                session_id,
                data["incomingCallContext"],
            )
            session.incoming_call_connection_id = result.call_connection_id
            logger.info("Answered incoming call for session %s", session_id)
        except Exception:
            logger.exception("Unable to answer incoming call")
            await session_manager.remove(session_id)
            return Response(status_code=500)

    return Response(status_code=200)


@app.post("/api/callbacks/{session_id}/{leg}")
async def call_callbacks(session_id: str, leg: str, request: Request):
    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    session = session_manager.get(session_id)
    if not session:
        logger.warning("Callback for unknown session %s", session_id)
        return Response(status_code=200)

    for event in events:
        event_type = event.get("type") or event.get("eventType", "")
        data = event.get("data", {})
        call_connection_id = data.get("callConnectionId")
        logger.info("Callback %s for %s/%s", event_type, session_id, leg)

        if event_type.endswith("CallConnected"):
            if leg == "incoming":
                session.incoming_connected = True
                session.incoming_call_connection_id = (
                    call_connection_id or session.incoming_call_connection_id
                )
                async with session.state_lock:
                    should_start = not session.outbound_started
                    if should_start:
                        session.outbound_started = True
                if should_start:
                    try:
                        result = await asyncio.to_thread(
                            acs_manager.create_outbound_call,
                            session_id,
                            session.outbound_phone_number,
                        )
                        session.outbound_call_connection_id = result.call_connection_id
                        logger.info("Outbound call created for session %s", session_id)
                    except Exception:
                        logger.exception("Unable to create outbound call")
                        await cleanup_session(session_id)
            elif leg == "outbound":
                session.outbound_connected = True
                session.outbound_call_connection_id = (
                    call_connection_id or session.outbound_call_connection_id
                )

        elif event_type.endswith("CallDisconnected"):
            asyncio.create_task(cleanup_session(session_id))

    return Response(status_code=200)


@app.websocket("/ws/media/{session_id}/{leg}")
async def media_websocket(websocket: WebSocket, session_id: str, leg: str):
    if leg not in {"incoming", "outbound"}:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session = session_manager.get(session_id)
    if not session:
        await websocket.close(code=1008)
        return

    if leg == "incoming":
        session.incoming_media_ws = websocket
    else:
        session.outbound_media_ws = websocket

    logger.info("ACS media WebSocket connected for %s/%s", session_id, leg)
    await ensure_translation_sessions(session)

    try:
        while True:
            message = await websocket.receive()
            if message.get("text") is not None:
                await handle_acs_media_message(session, leg, message["text"])
            elif message.get("bytes") is not None:
                await route_pcm_audio(session, leg, message["bytes"])
    except WebSocketDisconnect:
        logger.info("ACS media WebSocket disconnected for %s/%s", session_id, leg)
    except Exception:
        logger.exception("ACS media WebSocket failed for %s/%s", session_id, leg)
    finally:
        if leg == "incoming" and session.incoming_media_ws is websocket:
            session.incoming_media_ws = None
        elif leg == "outbound" and session.outbound_media_ws is websocket:
            session.outbound_media_ws = None


async def cleanup_session(session_id: str) -> None:
    session = session_manager.get(session_id)
    if not session:
        return

    async with session.state_lock:
        if session.closing:
            return
        session.closing = True

    for translator in (
        session.incoming_to_outbound_translator,
        session.outbound_to_incoming_translator,
    ):
        if translator:
            try:
                await translator.close()
            except Exception:
                logger.exception("Translator cleanup failed")

    for call_id in (
        session.incoming_call_connection_id,
        session.outbound_call_connection_id,
    ):
        if call_id:
            try:
                await asyncio.to_thread(acs_manager.hang_up, call_id)
            except Exception:
                logger.info("Call %s was already disconnected", call_id)

    await session_manager.remove(session_id)
    logger.info("Session %s cleaned up", session_id)
