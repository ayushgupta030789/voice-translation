import os


class Settings:
    acs_connection_string = os.getenv("ACS_CONNECTION_STRING")
    acs_phone_number = os.getenv("ACS_PHONE_NUMBER")
    public_https_base = os.getenv("PUBLIC_HTTPS_BASE")
    public_wss_base = os.getenv("PUBLIC_WSS_BASE")

    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_realtime_deployment = os.getenv(
        "AZURE_OPENAI_REALTIME_DEPLOYMENT",
        "gpt-realtime-translate"
    )
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")

    outbound_phone_number = os.getenv("OUTBOUND_PHONE_NUMBER")


settings = Settings()
