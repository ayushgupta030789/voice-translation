import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    acs_connection_string: str = os.getenv("ACS_CONNECTION_STRING", "")
    acs_phone_number: str = os.getenv("ACS_PHONE_NUMBER", "")
    target_phone_number: str = os.getenv("TARGET_PHONE_NUMBER", "")

    public_base_url: str = os.getenv(
        "PUBLIC_BASE_URL", "https://your-aca-app.azurecontainerapps.io"
    )

    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_deployment_name: str = os.getenv(
        "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-realtime-translate"
    )

    language_a: str = os.getenv("LANGUAGE_A", "hi")
    language_b: str = os.getenv("LANGUAGE_B", "en")

    # Optional: use Entra ID instead of API key.
    use_entra_id: bool = os.getenv("USE_ENTRA_ID", "false").lower() == "true"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/callbacks"

    @property
    def incoming_call_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/api/incoming-call"

    def acs_ws_url(self, session_id: str, leg: str) -> str:
        return f"{self.public_base_url.rstrip('/').replace('https://', 'wss://').replace('http://', 'ws://')}/ws/acs/{session_id}/{leg}"


settings = Settings()
