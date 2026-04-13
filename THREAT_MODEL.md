# Threat Model

## Scope

This threat model covers the local virtual smart home stack and its supporting services:

- `vshome/` smart-home UI and device state API
- `ollama_proxy/` model gateway, tool-call parser, wake-word flow, and protected-action bridge
- `deepface_service/` face-recognition authorization service and its abstract MySQL-backed datastore
- `whisper_service/` speech-to-text service
- `kitten_tts_service/` text-to-speech service

Assumptions for this model:

- Cloud-side accounts already exist and are managed outside this codebase.
- Requests to cloud services are authenticated and attributable to a user or service identity.
- Transport is protected with HTTPS/TLS between cloud and local endpoints where applicable.
- Non-repudiation exists for cloud-side requests and logs.

## Assets

Primary assets:

- Smart-home device state, especially doors, locks, thermostat, and other physical-world controls.
- Enrolled face records and access policy in the DeepFace datastore.
- Authorization audit records in the DeepFace datastore.
- Whisper model files and uploaded audio content.
- KittenTTS cache database and generated speech artifacts.
- Ollama model access, prompt history, and tool-call outputs.
- Camera and microphone inputs from the local operator device.

## Entry Points

Network-facing entry points:

- `http://localhost:8080` (smart home state and UI) and `ws://localhost:8080/ws` for the virtual smart home UI and API.
    - `ws`: web socket to the browser, just used as the demo frontend.
- `http://localhost:8090` for the Ollama proxy and tool bridge.
- `http://localhost:8100/v1/audio/transcriptions` for Whisper.
- `http://localhost:8110/v1/audio/speech` for KittenTTS.
- `http://localhost:8120/auth/authorize` for DeepFace authorization.
- `http://localhost:11434` for Ollama.
    - Secured transport for Ollama's cloud models.

Local resources:

- Webcam at `/dev/video0` exposed to `ollama_proxy`.
    - Emulating a security camera.
- Persistent state for Ollama, Whisper, and KittenTTS.
- Credentials and connectivity for the DeepFace datastore.

## Trust Boundaries

1. Browser to `vshome`.
    - Assumed local/on-device access
2. Browser to `ollama_proxy`.
    - Assumed local/on-device access, proxy handles security out
3. `ollama_proxy` to `vshome`, `whisper_service`, `kitten_tts_service`, `deepface_service`, and `ollama`.
4. `deepface_service` to the authorization service and datastore.
5. `whisper_service` and `kitten_tts_service` to model caches on disk.
6. Local host/container boundary for hardware device access and persistent storage.
7. Cloud identity boundary for externally managed accounts and request attribution.

## Data Flows

Representative flows:

1. User speaks or types a command in the browser UI (emulating smart home terminal).
2. `ollama_proxy` forwards the prompt to Ollama with device state context.
3. Ollama returns a tool call or text response.
4. The proxy parses the tool call and translates it into a `vshome` REST or WebSocket update.
5. For protected actions, `ollama_proxy` captures a webcam frame and sends it to `deepface_service`.
    - Based on tool action and auth list, not the model to request authorization.
6. `deepface_service` compares the frame against enrolled face records and evaluates policy from the datastore.
7. `ollama_proxy` writes the state change only if authorization succeeds.
8. `whisper_service` receives audio uploads and returns transcripts.
    - Currently unused, `ollama_proxy` just uses a browser API.
9. `kitten_tts_service` generates or returns cached speech audio.

## Threat Summary

### 1. Unauthorized control of physical-world actions

Relevant code paths:

- `ollama_proxy/main.py` protected actions and tool execution
- `vshome/main.go` device state mutation API

Threat:

- An attacker may trigger unlock, open, or thermostat changes without a valid authorization decision.

Why this matters:

- These are the only actions in the system that can affect real-world safety or privacy.

Controls:

- `ollama_proxy` checks `AUTH_ENABLED` and requests webcam-based authorization for protected actions.
- `deepface_service` validates the request payload and checks action policy per recognized person.

Residual risk:

- If `ollama_proxy` is compromised, an attacker may still call the local device API directly.
- `vshome` currently trusts any caller on its exposed interface.

Mitigations:

- Restrict `vshome` to the local Docker network or a private interface.
- Add authentication or signed requests to device mutation endpoints.
- Keep the authorization allowlist minimal and specific per person and per action.

### 2. Prompt injection or model-driven unsafe tool calls

Relevant code paths:

- `ollama_proxy/main.py` prompt assembly, tool-call extraction, and execution loop

Threat:

- A malicious user prompt or model output may cause unintended device updates or repeated tool invocations.

Controls:

- The proxy validates tool call shape before executing updates.
- Protected actions require a separate authorization step.

Residual risk:

- The model can still be manipulated into selecting the wrong device or state.
- The proxy currently infers device IDs and states from free-form prompts, which increases ambiguity.

Mitigations:

- Treat the model as untrusted and keep validation deterministic in the proxy.
- Require explicit device IDs for destructive or high-impact commands.
    - Impactful calls can also require auth apart from model intent.
- Add per-action confirmation for ambiguous updates.
    - The model doesn't always have to act, and has been shown to not.
- Log raw model output and final resolved tool calls for investigation.
    - Done in testing including intended action success rates.

### 3. Insecure or overly broad local API exposure

Relevant code paths:

- `vshome/main.go` HTTP and WebSocket handlers
- `whisper_service/main.py`
- `kitten_tts_service/main.py`
- `deepface_service/main.py`

Threat:

- Any host that can reach the exposed ports may use the APIs directly.

Controls:

- Services validate payload shape and some business rules.
- Docker Compose publishes ports intentionally for the demo environment.

Residual risk:

- There is no explicit authentication on the local APIs.
- `vshome` allows `PUT /api/devices/{id}` from any caller.
- WebSocket origin checks are permissive in `vshome`.

Mitigations:

- Bind services to localhost or a private Docker network when possible.
- Put an authenticating reverse proxy in front of external-facing services.
    - E.g., nginx
- Add origin and authentication checks to WebSocket and REST endpoints.

### 4. Face-recognition bypass or false acceptance

Relevant code paths:

- `deepface_service/service.py`

Threat:

- An attacker may present a spoofed face, a photo, a video replay, or a false-positive frame.

Controls:

- Policy is evaluated per person and per action from the database-backed policy store.
- Authorization decisions are logged.
- Require multiple frames or challenge-response verification for protected actions.

Residual risk:

- The implementation is single-frame recognition without liveness detection.
- `DEEPFACE_ENFORCE_DETECTION=false` by default reduces rejection of poor frames but may widen the acceptance surface.
    - Currently done due to webcam quality.

Mitigations:

- Add liveness or anti-spoofing checks if the system leaves a demo setting.
    - Built-in to DeepFace.
- Review the default detector backend and detection-enforcement settings for the intended deployment.

### 5. Weaknesses in auditability and non-repudiation

Relevant code paths:

- `deepface_service/service.py` audit log
- `ollama_proxy/main.py` tool execution and protected-action flow

Threat:

- There is no interface built-in to audit logs either for the local or cloud side.

Assumption:

- Cloud-side requests are assumed to have non-repudiation already, but the local edge still needs durable records.

Residual risk:

- The DeepFace audit records are not cryptographically protected by default.
    - Can be secured in the deployment.
- There is no evidence chain linking a cloud request, a model decision, the webcam frame, and the final local state update. Specifically, the image data is not logged due to the current data format.

Mitigations:

- Ship logs to an external append-only store.
- Add request IDs and decision IDs across the proxy and authorization service.
- Hash or sign authorization records if later dispute resolution is important.

### 6. Model and cache supply-chain exposure

Relevant code paths:

- `ollama_proxy/main.py` model resolution and Ollama API use
- `whisper_service/service.py`
- `kitten_tts_service/service.py`

Threat:

- Model downloads or cached artifacts could be malicious, corrupted, or unexpectedly changed.

Controls:

- Services restrict some request parameters to the configured model.
- KittenTTS and Whisper use local caches and model directories.
- Ollama uses checksums for model layers

Residual risk:

- `ollama:latest` is used in Compose, which is mutable. Could be bound to a specific hash.
- Model directories and cache stores are writable at runtime, required for model downloads

Mitigations:

- Pin image tags and model revisions (hash) where possible.
- Validate model provenance before deployment.
- Use read-only mounts for runtime code and narrow write permissions for caches.

### 7. Denial of service through large uploads or repeated model calls

Relevant code paths:

- `whisper_service/main.py`
- `kitten_tts_service/main.py`
- `ollama_proxy/main.py`

Threat:

- An attacker may send oversized audio, long text, repeated requests, or prompt loops that consume GPU/CPU/RAM.

Controls:

- Whisper enforces a maximum upload size before finishing the upload write.
- KittenTTS enforces maximum input length and voice/speed validation.
- The proxy limits the Ollama context size.

Residual risk:

- Repeated valid requests can still exhaust local compute and queue resources.
- The proxy can call downstream services multiple times during one user request.

Mitigations:

- Add rate limiting per client and per action. Again, nginx.
- Add timeouts and circuit breakers for downstream calls. Built in to some services.
- Cache or debounce repeated transcriptions and syntheses where safe.

### 8. WebSocket and browser-side abuse

Relevant code paths:

- `vshome/main.go` WebSocket upgrader
- `vshome/web/app.js`

Threat:

- A malicious website or browser session may connect to the local WebSocket and drive device state if the browser has access to the service.

Controls:

- The UI mainly updates state from backend messages.
- The frontend does not directly execute arbitrary script from device data.

Residual risk:

- `CheckOrigin` returns `true`, so cross-site WebSocket connections are allowed.
- There is no user authentication in the demo UI.

Mitigations:

- Enforce origin checks and session authentication on WebSocket connections.
- Avoid exposing the service on interfaces reachable by untrusted browser contexts.

