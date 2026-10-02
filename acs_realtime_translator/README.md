# ACS PSTN Real-Time Translation Bridge

Python/FastAPI proof of concept for this flow:

1. A PSTN caller calls an Azure Communication Services number.
2. Event Grid invokes `POST /api/incoming-call`.
3. ACS Call Automation answers the call and starts bidirectional media streaming.
4. The application creates a separate outbound PSTN call.
5. Two `gpt-realtime-translate` WebSocket sessions translate audio in both directions.

## Architecture

```text
Caller A -> ACS inbound media WSS -> translation A-to-B -> ACS outbound media WSS -> Caller B
Caller B -> ACS outbound media WSS -> translation B-to-A -> ACS inbound media WSS -> Caller A
```

The two PSTN calls are intentionally kept as separate call legs. ACA is the controlled audio bridge.

## Project layout

```text
acs_realtime_translator/
├── app/
│   ├── __init__.py
│   ├── acs_manager.py
│   ├── acs_media.py
│   ├── config.py
│   ├── main.py
│   ├── models.py
│   ├── realtime_translate.py
│   └── session_manager.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
└── requirements.txt
```

## Prerequisites

- Python 3.11+
- Azure Communication Services resource and PSTN-capable phone number
- Microsoft Foundry/Azure OpenAI deployment named `gpt-realtime-translate`
- Azure Container Apps application with external HTTPS ingress
- Event Grid subscription for `Microsoft.Communication.IncomingCall`

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Populate `.env`, then run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```text
GET /health
```

## Event Grid endpoint

Configure the ACS Incoming Call event subscription endpoint as:

```text
https://YOUR_APP/api/incoming-call
```

The application handles Event Grid subscription validation automatically.

## ACA ingress

Configure:

- External ingress: enabled
- Target port: `8000`
- Transport: Auto
- HTTPS: enabled
- WebSocket support: enabled through ACA ingress

For initial validation, keep one replica so the HTTP callbacks and both WebSockets share the same in-memory session state. Before scaling out, use Redis/distributed state and an explicit routing strategy.

## Build and run with Docker

```bash
docker build -t acs-realtime-translator .
docker run --rm -p 8000:8000 --env-file .env acs-realtime-translator
```

## Important validation points

This repository is a starting implementation. Before production use, validate these items against the exact installed SDK and deployed API version:

1. `MediaStreamingOptions` argument names in your installed `azure-communication-callautomation` package.
2. The ACS WebSocket `AudioData` input/output envelope and casing.
3. The `gpt-realtime-translate` session configuration fields and returned audio-delta event type.
4. Whether your Foundry deployment uses `/openai/realtime?api-version=...&deployment=...` or `/openai/v1/realtime?model=...`.
5. The PCM format from ACS metadata matches the model requirement: PCM signed 16-bit, 24 kHz, mono, little-endian, and no WAV header.
6. PSTN and media-streaming availability for your ACS subscription, country and current Microsoft product terms.

## Production improvements

- Use managed identity rather than API keys where supported.
- Put secrets in Azure Key Vault.
- Replace in-memory sessions with Redis.
- Add callback idempotency and distributed locking.
- Add outbound no-answer and setup timeout handling.
- Add bounded audio queues and backpressure.
- Add Application Insights/OpenTelemetry tracing.
- Add model and WebSocket reconnect handling.
- Add legally required call recording/translation notices and consent.
- Redact logs and do not log raw audio or sensitive transcripts.
