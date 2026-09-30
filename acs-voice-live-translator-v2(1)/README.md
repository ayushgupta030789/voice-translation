# ACS + GPT Realtime Translation — Python / Azure Container Apps

This project is a corrected v2 reference implementation for:

    PSTN A
      |
      v
     ACS
      |
      v
 Azure Container Apps / FastAPI
      |
      +---- ACS PSTN B
      |
      +---- gpt-realtime-translate
              |
              +---- A -> B
              +---- B -> A

## Important architecture

ACS Call Automation handles:

- incoming call
- answer call
- outbound PSTN call
- call lifecycle callbacks

ACS bidirectional media streaming handles:

- PCM audio from the PSTN call to ACA
- translated PCM audio from ACA back into the PSTN call

The Azure OpenAI / Microsoft Foundry Realtime Translation endpoint handles:

- continuous speech translation
- translated audio output
- translation text events

The project intentionally uses the dedicated Realtime Translation WebSocket rather than
the `azure-ai-voicelive` assistant SDK.

## Project layout

    app.py
    config.py

    acs/
      call_manager.py
      media.py

    realtime/
      translator.py

    session/
      call_session.py

    Dockerfile
    requirements.txt
    .env.example

## Phase flow

### Phase 1

    GET /health

### Phase 2

    Incoming PSTN
       |
       v
    /api/incoming-call
       |
       +--> answer incoming call
       |
       +--> create outbound PSTN call

### Phase 3

    ACS A --> /ws/acs/<session>/a
    ACS B --> /ws/acs/<session>/b

### Phase 4

    A audio
       |
       v
    gpt-realtime-translate
       |
       v
    B ACS WebSocket

    B audio
       |
       v
    gpt-realtime-translate
       |
       v
    A ACS WebSocket

## Environment

Copy `.env.example` to `.env`.

Minimum configuration:

    ACS_CONNECTION_STRING
    ACS_PHONE_NUMBER
    TARGET_PHONE_NUMBER
    PUBLIC_BASE_URL

    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_DEPLOYMENT_NAME

    LANGUAGE_A
    LANGUAGE_B

Example:

    LANGUAGE_A=hi
    LANGUAGE_B=en

## Azure OpenAI / Foundry endpoint

The translation client uses:

    wss://<resource>/openai/v1/realtime/translations?model=<deployment>

The deployment name is the value of:

    AZURE_OPENAI_DEPLOYMENT_NAME

The project configures 24-kHz PCM audio.

## ACS media

The project uses:

    StreamingTransportType.WEBSOCKET
    MediaStreamingContentType.AUDIO
    MediaStreamingAudioChannelType.UNMIXED
    AudioFormat.PCM24_K_MONO
    enable_bidirectional=True
    start_media_streaming=True

ACS sends JSON WebSocket messages. AudioData contains base64 encoded PCM.

## Event Grid

Configure the ACS Incoming Call Event Grid subscription to:

    https://<ACA-HOST>/api/incoming-call

The application handles Event Grid SubscriptionValidationEvent.

ACS Call Automation callback events use:

    https://<ACA-HOST>/api/callbacks

## Important: one ACA replica initially

The session store is in process memory:

    sessions = SessionStore()

Therefore start with:

    min replicas = 1
    max replicas = 1

For production scale-out, move call/session state to a distributed store and design
WebSocket affinity/routing explicitly.

## Recommended test order

1. Deploy ACA.
2. Test GET /health.
3. Test POST /test.
4. Test Event Grid validation.
5. Test incoming PSTN answer.
6. Test outbound PSTN call.
7. Verify both CallConnected callbacks.
8. Verify both ACS WebSockets.
9. Verify Realtime Translation session.updated.
10. Speak Hindi on A and verify English output on B.
11. Speak English on B and verify Hindi output on A.
12. Test hang-up from either side.

## Troubleshooting

Look for these log stages:

    Incoming call received
    Incoming call answered
    Outbound call created
    Call A connected
    Call B connected
    ACS media A connected
    ACS media B connected
    Translation session configured A->B
    Translation session configured B->A
    response.output_audio.delta
    Call leg ended

If the call works but there is no audio:

1. Check both `/ws/acs/...` connections.
2. Check ACS AudioMetadata.
3. Check AudioData events.
4. Check Realtime `session.updated`.
5. Check Realtime `error` events.
6. Check that the model deployment is actually `gpt-realtime-translate`.
7. Check that the target language is a supported language code.

## Production hardening still required

This is a reference implementation, not a production-ready carrier-grade bridge.

Before production, add:

- distributed session state
- authentication/authorization for callback and WebSocket endpoints
- managed identity / Key Vault instead of plain API keys
- WebSocket authentication strategy
- call-id/session correlation persistence
- reconnect/retry strategy
- backpressure handling
- media queueing
- latency monitoring
- metrics/tracing
- graceful handling of partial call setup
- DDoS/rate-limit protections
- multi-replica WebSocket routing
- robust shutdown and cancellation
