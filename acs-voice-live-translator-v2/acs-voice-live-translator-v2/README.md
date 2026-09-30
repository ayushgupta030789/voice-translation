# ACS PSTN Interpreter — Python / ACA / GPT Realtime Translate (v2)

This is a **starter/reference implementation** for a two-party PSTN interpreter:

- Caller A calls an ACS phone number.
- ACS IncomingCall is delivered to `/api/incoming-call` through Event Grid.
- ACA answers Caller A and places an outbound call to Caller B.
- ACS opens one bidirectional media WebSocket per call leg.
- Each leg's 24 kHz mono PCM16 audio is sent to a dedicated `gpt-realtime-translate` translation session.
- The dedicated translation endpoint returns translated text events; Azure Speech TTS converts completed translated text segments to 24 kHz PCM16, which ACA streams to the opposite ACS leg.

## Important protocol choice

This implementation uses the documented dedicated Realtime Translation endpoint:

`wss://<resource>.services.ai.azure.com/openai/v1/realtime/translations?model=<deployment>`

It does **not** use `azure-ai-voicelive`, because this project uses the translation session type rather than a Voice Live assistant session. The translation example in Microsoft's Realtime WebSocket guide handles `response.text.delta` and `response.text.done`; therefore this implementation uses Azure Speech TTS to speak the translated text. It does not assume the translation endpoint returns audio deltas.

Official references:
- Realtime WebSocket / translation example: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-websockets
- ACS bidirectional audio streaming: https://learn.microsoft.com/en-us/azure/communication-services/concepts/call-automation/audio-streaming-concept
- ACS Python SDK: https://learn.microsoft.com/en-us/python/api/overview/azure/communication-callautomation-readme

## Files

```text
app.py                         Quart HTTP callbacks + WebSocket routes
config.py                      Environment variables and endpoint builders
acs/call_manager.py            ACS answer/create/hangup operations
acs/media.py                   ACS media packet handling and audio output
realtime/translator.py         gpt-realtime-translate WebSocket client
realtime/speech_synthesizer.py Azure Speech TTS adapter
session/call_session.py        Call correlation, queues, pumps, teardown
requirements.txt
Dockerfile
deploy-aca.ps1
.env.example
```

## Configuration

Copy `.env.example` to `.env` for local reference, then configure the same variables as Container App environment variables/secrets. The application does not automatically load `.env` inside ACA.

Required settings:

- `ACS_CONNECTION_STRING`
- `ACS_PHONE_NUMBER` — ACS number used as outbound caller ID
- `TARGET_PHONE_NUMBER` — destination PSTN number B
- `PUBLIC_BASE_URL` — externally reachable HTTPS ACA ingress URL
- `AZURE_OPENAI_ENDPOINT` — Foundry/Azure OpenAI resource endpoint
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT_NAME` — the deployment name, normally `gpt-realtime-translate`
- `SPEECH_KEY`, `SPEECH_REGION`

Language/voice settings:

- `LANGUAGE_A=hi`, `LANGUAGE_B=en`
- `SPEECH_VOICE_A=hi-IN-SwaraNeural`
- `SPEECH_VOICE_B=en-US-JennyNeural`

Caller A's speech is translated to `LANGUAGE_B` and spoken to caller B. Caller B's speech is translated to `LANGUAGE_A` and spoken to caller A.

## Azure configuration

1. Deploy a `gpt-realtime-translate` model in Microsoft Foundry and use its **deployment name** in `AZURE_OPENAI_DEPLOYMENT_NAME`.
2. Give the ACA managed identity/credential the required data-plane role if using Entra auth in a future version. This starter currently uses an API key.
3. Create an Azure Speech resource and configure its key/region. Use Key Vault or ACA secrets for secrets; do not commit them.
4. Publish the ACA app with HTTPS ingress and WebSocket support. `PUBLIC_BASE_URL` must be reachable from ACS over the network path you have configured.
5. Configure an Event Grid subscription for `Microsoft.Communication.IncomingCall` to `https://<ACA-host>/api/incoming-call`. Complete Event Grid endpoint validation.
6. Ensure the ACS phone number can receive PSTN calls and is authorized for outbound PSTN calling to the destination.
7. Start with one replica. The in-memory session map requires the call event and both media WebSockets to land on the same replica. This is a prototype limitation.

## Local run

Use Python 3.11. Set environment variables in your shell (do not commit `.env`), then:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
hypercorn app:app --bind 0.0.0.0:8080 --workers 1
```

Health checks:

```powershell
curl.exe https://YOUR-ACA-HOST/health
curl.exe -X POST https://YOUR-ACA-HOST/test
```

## Deploying

The included `deploy-aca.ps1` demonstrates a basic ACR build/deploy workflow. It assumes ACR Tasks are enabled and Azure CLI/containerapp extension are configured. If your registry has `TasksOperationsNotAllowed`, this script's `az acr build` step will fail; use your approved external build workflow and push the image instead.

After deploying, set the environment variables and secrets in ACA. Example (adapt names and protect secrets):

```powershell
az containerapp secret set -g YOUR-RG -n YOUR-APP --secrets `
  acs-connection-string="YOUR-ACS-CONNECTION-STRING" `
  openai-api-key="YOUR-KEY" `
  speech-key="YOUR-SPEECH-KEY"

az containerapp update -g YOUR-RG -n YOUR-APP --set-env-vars `
  ACS_CONNECTION_STRING=secretref:acs-connection-string `
  AZURE_OPENAI_API_KEY=secretref:openai-api-key `
  SPEECH_KEY=secretref:speech-key `
  ACS_PHONE_NUMBER=+15551230001 `
  TARGET_PHONE_NUMBER=+15551230002 `
  PUBLIC_BASE_URL=https://YOUR-ACA-HOST `
  AZURE_OPENAI_ENDPOINT=https://YOUR-FOUNDRY-RESOURCE.services.ai.azure.com `
  AZURE_OPENAI_DEPLOYMENT_NAME=gpt-realtime-translate `
  SPEECH_REGION=eastus2 `
  LANGUAGE_A=hi LANGUAGE_B=en `
  SPEECH_VOICE_A=hi-IN-SwaraNeural SPEECH_VOICE_B=en-US-JennyNeural
```

## Test phases

1. **ACA only:** `/health` and `/test` return success.
2. **Call control:** test Event Grid validation, then a real incoming call; confirm the inbound leg is answered and outbound PSTN leg rings/connects.
3. **Media:** confirm `AudioMetadata` logs for both `/ws/acs/<session>/a` and `/ws/acs/<session>/b`; metadata should report PCM and 24000 Hz.
4. **Translation:** confirm translation session setup, `response.text.done` translated segments, Speech synthesis success, and audio frames sent to the opposite ACS leg.

## Important limitations before production

- This is a starter project and has **not** been exercised against your live ACS, Foundry deployment, Speech resource, PSTN numbers, or private network.
- SDK signatures can vary by installed `azure-communication-callautomation` version. Verify `answer_call`, `create_call`, and `MediaStreamingOptions` against the installed SDK. In particular, confirm the installed Python SDK's `create_call` supports `media_streaming`; if not, create the outbound call then invoke the call media start-streaming operation on its connection.
- TTS is performed on completed translated text segments, not as a token-by-token speech stream. This is simpler to validate but adds latency and may sound segmented. Optimize with streaming TTS after validating correctness.
- A language code such as `hi`/`en` configures the translation target, while Azure Speech uses locale/voice names. Validate model-supported target languages and desired voice names in your region.
- The first-party media streaming protocol must be tested with actual ACS packets. This project logs metadata and assumes the media payload is PCM16 mono 24 kHz because `PCM24KMono` is configured.
- Session state is in process memory; one replica only. Production should use durable session coordination, authenticated callback validation, call idempotency, cancellation handling, observability, and secure secret management.
- Implement and test failure policy (outbound no-answer, busy, one leg disconnect, model outage, speech synthesis outage) before production use.
