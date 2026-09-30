import asyncio
import json
import logging
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from acs.call_manager import acs_manager
from acs.media import receive_acs_audio, send_acs_audio
from config import settings
from realtime.translator import RealtimeTranslator
from session.call_session import CallSession, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("acs-voice-live-translator")

app = FastAPI(title="ACS GPT Realtime Translator")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "acs-voice-live-translator",
    }


@app.post("/test")
async def test():
    return {"status": "OK"}


def extract_event_type(event: dict) -> str:
    return event.get("type", "")


@app.post("/api/incoming-call")
async def incoming_call(request: Request):
    """
    Event Grid endpoint for ACS incoming-call events.

    This endpoint also supports Event Grid's validation handshake.
    """
    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    # Event Grid validation handshake.
    for event in events:
        data = event.get("data", {})
        if event.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return JSONResponse({
                "validationResponse": data.get("validationCode")
            })

    for event in events:
        event_type = extract_event_type(event)

        if event_type not in (
            "Microsoft.Communication.IncomingCall",
            "Microsoft.Communication.IncomingCallEvent",
            "Microsoft.Communication.CallIncoming",
        ):
            logger.info("Ignoring incoming endpoint event type=%s", event_type)
            continue

        data = event.get("data", {})
        incoming_call_context = (
            data.get("incomingCallContext")
            or data.get("incomingCallContextToken")
        )

        if not incoming_call_context:
            logger.error("Incoming call event did not contain incomingCallContext: %s", event)
            continue

        session_id = str(uuid.uuid4())
        session = CallSession(
            session_id=session_id,
            language_a=settings.language_a,
            language_b=settings.language_b,
        )
        sessions.create(session)

        logger.info("Created session %s", session_id)

        # Answer the inbound call. ACS will connect its media WebSocket
        # to /ws/acs/<session_id>/a.
        answer_result = await acs_manager.answer(
            incoming_call_context=incoming_call_context,
            callback_url=settings.callback_url,
            ws_url=settings.acs_ws_url(session_id, "a"),
        )

        session.incoming_call_connection = answer_result.call_connection
        session.incoming_call_id = answer_result.call_connection.call_connection_id

        logger.info(
            "Incoming call answered session=%s callConnectionId=%s",
            session_id,
            session.incoming_call_id,
        )

        # Create the second PSTN leg.
        outbound_result = await acs_manager.create_outbound(
            target_phone=settings.target_phone_number,
            source_phone=settings.acs_phone_number,
            callback_url=settings.callback_url,
            ws_url=settings.acs_ws_url(session_id, "b"),
        )

        session.outbound_call_connection = outbound_result.call_connection
        session.outbound_call_id = outbound_result.call_connection.call_connection_id

        logger.info(
            "Outbound call created session=%s callConnectionId=%s",
            session_id,
            session.outbound_call_id,
        )

    return {"status": "accepted"}


@app.post("/api/callbacks")
async def callbacks(request: Request):
    """
    ACS Call Automation callback endpoint.

    We use these events for lifecycle/call-leg diagnostics and teardown.
    """
    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    for event in events:
        event_type = event.get("type")
        data = event.get("data", {})

        logger.info(
            "ACS callback type=%s callConnectionId=%s",
            event_type,
            data.get("callConnectionId"),
        )

        call_id = data.get("callConnectionId")
        session = None

        if call_id:
            for candidate in sessions.all().values():
                if call_id in (
                    candidate.incoming_call_id,
                    candidate.outbound_call_id,
                ):
                    session = candidate
                    break

        if not session:
            continue

        if event_type == "Microsoft.Communication.CallConnected":
            if call_id == session.incoming_call_id:
                session.call_a_connected.set()
                logger.info("Call A connected session=%s", session.session_id)

            elif call_id == session.outbound_call_id:
                session.call_b_connected.set()
                logger.info("Call B connected session=%s", session.session_id)

            # Translation is intentionally started only after both
            # telephone legs have connected.
            if (
                session.call_a_connected.is_set()
                and session.call_b_connected.is_set()
            ):
                asyncio.create_task(start_translation_sessions(session))

        elif event_type in {
            "Microsoft.Communication.CallDisconnected",
            "Microsoft.Communication.CallEnded",
        }:
            logger.info("Call leg ended session=%s", session.session_id)
            asyncio.create_task(close_session(session))

    return {"status": "ok"}


async def start_translation_sessions(session: CallSession):
    """
    Start two translation sessions:
      A -> B : language A to language B
      B -> A : language B to language A

    This is idempotent.
    """
    if session.translator_a_to_b or session.translator_b_to_a:
        return

    # Wait for both media WebSockets too.
    try:
        await asyncio.wait_for(
            asyncio.gather(
                session.media_a_connected.wait(),
                session.media_b_connected.wait(),
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Translation not started because both ACS media sockets "
            "did not connect within 30 seconds. session=%s",
            session.session_id,
        )
        return

    async def a_to_b_audio(pcm: bytes):
        if session.ws_b:
            await send_acs_audio(session.ws_b, pcm)

    async def b_to_a_audio(pcm: bytes):
        if session.ws_a:
            await send_acs_audio(session.ws_a, pcm)

    async def text_a_to_b(text: str):
        logger.info("[A->B translation] %s", text)

    async def text_b_to_a(text: str):
        logger.info("[B->A translation] %s", text)

    session.translator_a_to_b = RealtimeTranslator(
        name=f"{session.session_id}:A->B",
        target_language=session.language_b,
        on_audio=a_to_b_audio,
        on_text=text_a_to_b,
    )

    session.translator_b_to_a = RealtimeTranslator(
        name=f"{session.session_id}:B->A",
        target_language=session.language_a,
        on_audio=b_to_a_audio,
        on_text=text_b_to_a,
    )

    await asyncio.gather(
        session.translator_a_to_b.connect(),
        session.translator_b_to_a.connect(),
    )

    logger.info(
        "Both translation sessions started session=%s",
        session.session_id,
    )


@app.websocket("/ws/acs/{session_id}/{leg}")
async def acs_media_websocket(
    websocket: WebSocket,
    session_id: str,
    leg: str,
):
    await websocket.accept()

    session = sessions.get(session_id)

    if not session or leg not in ("a", "b"):
        await websocket.close(code=1008)
        return

    if leg == "a":
        session.ws_a = websocket
        session.media_a_connected.set()
        logger.info("ACS media A connected session=%s", session_id)
    else:
        session.ws_b = websocket
        session.media_b_connected.set()
        logger.info("ACS media B connected session=%s", session_id)

    try:
        async for pcm in receive_acs_audio(websocket):
            if session.closed:
                break

            # Translation may not be ready yet while the PSTN legs are
            # connecting. We simply discard media until the translator
            # exists rather than blocking the ACS WebSocket.
            if leg == "a" and session.translator_a_to_b:
                await session.translator_a_to_b.send_audio(pcm)

            elif leg == "b" and session.translator_b_to_a:
                await session.translator_b_to_a.send_audio(pcm)

    except WebSocketDisconnect:
        logger.info(
            "ACS media WebSocket disconnected leg=%s session=%s",
            leg,
            session_id,
        )
    except Exception:
        logger.exception(
            "ACS media WebSocket failure leg=%s session=%s",
            leg,
            session_id,
        )
    finally:
        if leg == "a":
            session.ws_a = None
        else:
            session.ws_b = None


async def close_session(session: CallSession):
    if session.closed:
        return

    logger.info("Closing session=%s", session.session_id)
    session.closed = True

    # If either party hangs up, terminate the other leg.
    try:
        if session.incoming_call_connection:
            await acs_manager.hangup(session.incoming_call_connection)
    except Exception:
        pass

    try:
        if session.outbound_call_connection:
            await acs_manager.hangup(session.outbound_call_connection)
    except Exception:
        pass

    await session.close()
    sessions.remove(session.session_id)


@app.on_event("shutdown")
async def shutdown():
    for session in list(sessions.all().values()):
        await session.close()

    await acs_manager.close()
