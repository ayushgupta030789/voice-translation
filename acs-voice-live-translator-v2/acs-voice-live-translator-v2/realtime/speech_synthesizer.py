"""Azure Speech TTS adapter: translated text -> 24 kHz mono PCM16."""
import asyncio
import logging

import azure.cognitiveservices.speech as speechsdk

from config import SPEECH_KEY, SPEECH_REGION, SPEECH_VOICE_A, SPEECH_VOICE_B

logger = logging.getLogger(__name__)


def _synthesize_sync(text: str, voice: str) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
    )
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return bytes(result.audio_data)
    details = getattr(result, "cancellation_details", None)
    reason = getattr(details, "error_details", "unknown Speech synthesis error")
    raise RuntimeError(f"Speech synthesis failed: {reason}")


async def synthesize_translated_text(text: str, destination_side: str) -> bytes:
    voice = SPEECH_VOICE_B if destination_side == "b" else SPEECH_VOICE_A
    return await asyncio.to_thread(_synthesize_sync, text, voice)
