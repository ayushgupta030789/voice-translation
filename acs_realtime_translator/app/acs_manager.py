from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    PhoneNumberIdentifier,
    StreamingTransportType,
)
from app.config import get_settings


class ACSManager:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = CallAutomationClient.from_connection_string(
            settings.acs_connection_string
        )
        self.source_number = PhoneNumberIdentifier(settings.acs_phone_number)

    def _media_options(self, session_id: str, leg: str) -> MediaStreamingOptions:
        transport_url = (
            f"{self.settings.public_wss_base.rstrip('/')}"
            f"/ws/media/{session_id}/{leg}"
        )
        return MediaStreamingOptions(
            transport_url=transport_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM24_K_MONO,
        )

    def answer_incoming_call(self, session_id: str, incoming_call_context: str):
        callback_url = (
            f"{self.settings.public_https_base.rstrip('/')}"
            f"/api/callbacks/{session_id}/incoming"
        )
        return self.client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_url,
            media_streaming=self._media_options(session_id, "incoming"),
        )

    def create_outbound_call(self, session_id: str, target_phone_number: str):
        callback_url = (
            f"{self.settings.public_https_base.rstrip('/')}"
            f"/api/callbacks/{session_id}/outbound"
        )
        return self.client.create_call(
            target_participant=PhoneNumberIdentifier(target_phone_number),
            source_caller_id_number=self.source_number,
            callback_url=callback_url,
            media_streaming=self._media_options(session_id, "outbound"),
        )

    def hang_up(self, call_connection_id: str) -> None:
        connection = self.client.get_call_connection(call_connection_id)
        connection.hang_up(is_for_everyone=True)


acs_manager = ACSManager()
