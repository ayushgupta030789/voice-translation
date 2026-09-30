import asyncio
import logging
import uuid

from quart import Quart, jsonify, request

from acs.call_manager import answer_incoming_call, create_outbound_call, hangup_call, close_client
from acs.media import receive_acs_media
from config import PORT, validate_required
from session.call_session import CallSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("acs-voice-live-translator")
app = Quart(__name__)
sessions: dict[str, CallSession] = {}


@app.before_serving
async def startup():
    validate_required()
    logger.info("Application started; deployment=%s", __import__("config").AZURE_OPENAI_DEPLOYMENT_NAME)


@app.after_serving
async def shutdown():
    for session_id in list(sessions):
        await cleanup_session(session_id, hangup=False)
    await close_client()


@app.get("/health")
async def health():
    return jsonify({"status": "ok", "application": "acs-voice-live-translator-v2"})


@app.post("/test")
async def test():
    return jsonify({"status": "OK"})


@app.post("/api/incoming-call")
async def incoming_call():
    """Event Grid webhook for Microsoft.Communication.IncomingCall."""
    body = await request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Expected JSON"}), 400
    events = body if isinstance(body, list) else [body]
    results = []

    for event in events:
        event_type = event.get("eventType") or event.get("type")
        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            code = event.get("data", {}).get("validationCode")
            if not code:
                return jsonify({"error": "Missing validationCode"}), 400
            return jsonify({"validationResponse": code})

        if event_type != "Microsoft.Communication.IncomingCall":
            logger.info("Ignoring Event Grid event type=%s", event_type)
            continue

        incoming_context = event.get("data", {}).get("incomingCallContext")
        if not incoming_context:
            logger.error("IncomingCall event did not include incomingCallContext")
            continue

        session_id = str(uuid.uuid4())
        session = CallSession(session_id=session_id)
        sessions[session_id] = session
        try:
            answered = await answer_incoming_call(incoming_context, session_id)
            session.incoming_call_id = answered.call_connection_id
            logger.info("Incoming call answered session=%s call=%s", session_id, session.incoming_call_id)

            outbound = await create_outbound_call(session_id)
            session.outbound_call_id = outbound.call_connection_id
            logger.info("Outbound call initiated session=%s call=%s", session_id, session.outbound_call_id)
            results.append({
                "session_id": session_id,
                "incoming_call_id": session.incoming_call_id,
                "outbound_call_id": session.outbound_call_id,
            })
        except Exception:
            logger.exception("Failed to establish call legs session=%s", session_id)
            await cleanup_session(session_id, hangup=True)

    return jsonify({"status": "processed", "sessions": results})


@app.post("/api/callbacks/<session_id>")
async def callbacks(session_id: str):
    session = sessions.get(session_id)
    body = await request.get_json(silent=True)
    events = body if isinstance(body, list) else [body] if body else []
    for event in events:
        event_type = event.get("type") or event.get("eventType")
        data = event.get("data", {})
        call_id = data.get("callConnectionId")
        logger.info("ACS callback session=%s type=%s callConnectionId=%s", session_id, event_type, call_id)
        if event_type in {"Microsoft.Communication.CallDisconnected", "Microsoft.Communication.CallEnded"}:
            # Any leg disconnect ends the interpreter session and releases the other leg.
            asyncio.create_task(cleanup_session(session_id, hangup=True, disconnected_call_id=call_id))
    return jsonify({"status": "ok"})


@app.websocket("/ws/acs/<session_id>/<side>")
async def acs_websocket(session_id: str, side: str):
    if side not in {"a", "b"}:
        return
    session = sessions.get(session_id)
    if not session:
        logger.error("ACS connected to unknown session=%s side=%s", session_id, side)
        return
    await receive_acs_media(session, side)


async def cleanup_session(session_id: str, hangup: bool, disconnected_call_id: str | None = None):
    session = sessions.pop(session_id, None)
    if not session:
        return
    logger.info("Cleaning up session=%s", session_id)
    await session.close()
    if hangup:
        for call_id in (session.incoming_call_id, session.outbound_call_id):
            if call_id and call_id != disconnected_call_id:
                await hangup_call(call_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
