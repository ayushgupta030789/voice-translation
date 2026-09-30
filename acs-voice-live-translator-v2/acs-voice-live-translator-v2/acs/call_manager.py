import logging

from azure.core.credentials import AzureKeyCredential
from azure.communication.callautomation.aio import CallAutomationClient
from azure.communication.callautomation import (
    AudioFormat,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    PhoneNumberIdentifier,
)

from config import (
    ACS_CONNECTION_STRING,
    ACS_PHONE_NUMBER,
    TARGET_PHONE_NUMBER,
    callback_url,
    ws_url,
)

logger = logging.getLogger(__name__)


def _parse_connection_string(value: str) -> tuple[str, str]:
    parts = {}
    for item in value.split(";"):
        if "=" in item:
            key, val = item.split("=", 1)
            parts[key.strip().lower()] = val.strip()
    endpoint = parts.get("endpoint")
    access_key = parts.get("accesskey")
    if not endpoint or not access_key:
        raise RuntimeError("ACS_CONNECTION_STRING must contain Endpoint and accesskey")
    return endpoint, access_key


_endpoint, _key = _parse_connection_string(ACS_CONNECTION_STRING)
acs_client = CallAutomationClient(endpoint=_endpoint, credential=AzureKeyCredential(_key))


def media_options(session_id: str, side: str) -> MediaStreamingOptions:
    return MediaStreamingOptions(
        transport_url=ws_url(session_id, side),
        transport_type=MediaStreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=MediaStreamingAudioChannelType.MIXED,
        start_media_streaming=True,
        enable_bidirectional=True,
        audio_format=AudioFormat.PCM24_K_MONO,
    )


async def answer_incoming_call(incoming_call_context: str, session_id: str):
    return await acs_client.answer_call(
        incoming_call_context=incoming_call_context,
        callback_url=callback_url(session_id),
        operation_context=f"incoming-{session_id}",
        media_streaming=media_options(session_id, "a"),
    )


async def create_outbound_call(session_id: str):
    return await acs_client.create_call(
        target_participant=PhoneNumberIdentifier(TARGET_PHONE_NUMBER),
        callback_url=callback_url(session_id),
        source_caller_id_number=PhoneNumberIdentifier(ACS_PHONE_NUMBER),
        operation_context=f"outbound-{session_id}",
        media_streaming=media_options(session_id, "b"),
    )


async def hangup_call(call_connection_id: str | None) -> None:
    if not call_connection_id:
        return
    try:
        connection = acs_client.get_call_connection(call_connection_id)
        await connection.hang_up(is_for_everyone=True)
    except Exception:
        logger.exception("Could not hang up call connection %s", call_connection_id)


async def close_client() -> None:
    await acs_client.close()
