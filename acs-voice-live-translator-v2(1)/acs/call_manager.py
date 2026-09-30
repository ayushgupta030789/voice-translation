import logging
from typing import Optional

from azure.communication.callautomation.aio import CallAutomationClient
from azure.communication.callautomation import (
    PhoneNumberIdentifier,
    MediaStreamingOptions,
    StreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    AudioFormat,
)

from config import settings

logger = logging.getLogger(__name__)


class ACSCallManager:
    def __init__(self):
        if not settings.acs_connection_string:
            raise RuntimeError("ACS_CONNECTION_STRING is not configured")

        self.client = CallAutomationClient.from_connection_string(
            settings.acs_connection_string
        )

    def media_options(self, ws_url: str):
        return MediaStreamingOptions(
            transport_url=ws_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM24_K_MONO,
        )

    async def answer(self, incoming_call_context: str, callback_url: str, ws_url: str):
        logger.info("Answering incoming ACS call")
        result = await self.client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_url,
            media_streaming=self.media_options(ws_url),
        )
        return result

    async def create_outbound(
        self,
        target_phone: str,
        source_phone: str,
        callback_url: str,
        ws_url: str,
    ):
        logger.info("Creating outbound PSTN call to %s", target_phone)
        result = await self.client.create_call(
            target_participant=PhoneNumberIdentifier(target_phone),
            source_caller_id_number=source_phone,
            callback_url=callback_url,
            media_streaming=self.media_options(ws_url),
        )
        return result

    async def hangup(self, call_connection):
        if not call_connection:
            return
        try:
            await call_connection.hang_up(is_for_everyone=True)
        except Exception:
            logger.exception("Failed to hang up call")

    async def close(self):
        await self.client.close()


acs_manager = ACSCallManager()
