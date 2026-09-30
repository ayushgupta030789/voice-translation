import os
from urllib.parse import urlencode, urlparse


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

ACS_CONNECTION_STRING = env("ACS_CONNECTION_STRING")
ACS_PHONE_NUMBER = env("ACS_PHONE_NUMBER")
TARGET_PHONE_NUMBER = env("TARGET_PHONE_NUMBER")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL").rstrip("/")

AZURE_OPENAI_ENDPOINT = env("AZURE_OPENAI_ENDPOINT").rstrip("/")
AZURE_OPENAI_API_KEY = env("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = env("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-realtime-translate")

# Azure Speech is used to speak the translated text returned by the dedicated
# Realtime Translation endpoint. Configure a Speech resource in the same region
# or a region approved for your data path.
SPEECH_KEY = env("SPEECH_KEY")
SPEECH_REGION = env("SPEECH_REGION")
SPEECH_VOICE_A = env("SPEECH_VOICE_A", "hi-IN-SwaraNeural")
SPEECH_VOICE_B = env("SPEECH_VOICE_B", "en-US-JennyNeural")

LANGUAGE_A = env("LANGUAGE_A", "hi")
LANGUAGE_B = env("LANGUAGE_B", "en")
PORT = int(env("PORT", "8080"))

CALLBACK_PATH_TEMPLATE = "/api/callbacks/{session_id}"
WS_PATH_TEMPLATE = "/ws/acs/{session_id}/{side}"


def validate_required() -> None:
    required = {
        "ACS_CONNECTION_STRING": ACS_CONNECTION_STRING,
        "ACS_PHONE_NUMBER": ACS_PHONE_NUMBER,
        "TARGET_PHONE_NUMBER": TARGET_PHONE_NUMBER,
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
        "AZURE_OPENAI_ENDPOINT": AZURE_OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY": AZURE_OPENAI_API_KEY,
        "SPEECH_KEY": SPEECH_KEY,
        "SPEECH_REGION": SPEECH_REGION,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))


def callback_url(session_id: str) -> str:
    return PUBLIC_BASE_URL + CALLBACK_PATH_TEMPLATE.format(session_id=session_id)


def ws_url(session_id: str, side: str) -> str:
    parsed = urlparse(PUBLIC_BASE_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}" + WS_PATH_TEMPLATE.format(session_id=session_id, side=side)


def translation_ws_url() -> str:
    endpoint = AZURE_OPENAI_ENDPOINT
    if endpoint.lower().startswith("https://"):
        endpoint = "wss://" + endpoint[8:]
    elif endpoint.lower().startswith("http://"):
        endpoint = "ws://" + endpoint[7:]
    query = urlencode({"model": AZURE_OPENAI_DEPLOYMENT_NAME})
    return f"{endpoint}/openai/v1/realtime/translations?{query}"
