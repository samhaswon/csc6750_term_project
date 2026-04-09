# CSC6570 Term Project

Cloud security

## System Parts

Virtual smart home:
- Basically just a web page with virtual smart devices like lights, thermostat, door lock, etc.
  - The virtual devices are their own toggles
- Some way to view logs if not separated
- Camera feed

Base station:
- Ollama running locally to host the LLM
- Other models run within the local service
  - TTS? https://huggingface.co/collections/Qwen/qwen3-tts
- Whisper transcription service exposed over HTTP
- KittenTTS speech generation service with local cache
- Web cam and microphone of the device running the demo used as the "doorbell."

Cloud:
- Cloud model hosting
- Logging
- Database with relevant information
  - Images of people for the model to use
  - Audio samples
  - Whatever else the models need

## Quick start

```bash
sudo docker compose up -d --build
```

Virtual smart home UI: http://localhost:8080

Whisper transcription API: `http://localhost:8100/v1/audio/transcriptions`
KittenTTS speech API: `http://localhost:8110/v1/audio/speech`

## Ollama + FunctionGemma

- Ollama runs on `http://localhost:11434`.
- The smart home tool proxy runs on `http://localhost:8090`.

> [!NOTE]
> You must use localhost here for Chrome, otherwise it cannot use the microphone.

- Tool bridge endpoint: `POST /tools/smart_home` (see `ollama_proxy/README.md`).
- The Whisper service runs on `http://localhost:8100`.
- Health check: `GET /health`
- Transcription endpoint: `POST /v1/audio/transcriptions` (see `whisper_service/README.md`).
- The KittenTTS service runs on `http://localhost:8110`.
- Health check: `GET /health`
- Speech endpoint: `POST /v1/audio/speech` (see `kitten_tts_service/README.md`).

## Service Reference

### `kitten_tts_service/`

Local FastAPI text-to-speech service on `http://localhost:8110`.

- Main endpoint: `POST /v1/audio/speech`
- Health endpoint: `GET /health`
- Accepts JSON with `input`, optional `model`, optional `voice`, optional `speed`, and
  `response_format`
- Returns `audio/wav`
- Includes `X-Cache-Hit: 1` when the response comes from the SQLite cache

Key configuration:

- `KITTEN_MODEL`: configured model name, default `KittenML/kitten-tts-nano-0.8`
- `KITTEN_MODEL_DIR`: model cache directory
- `KITTEN_CACHE_DB`: SQLite cache path for generated audio
- `KITTEN_DEVICE`: `auto`, `cpu`, or `cuda`
- `KITTEN_DEFAULT_VOICE`: default voice name, default `Bella`
- `MAX_INPUT_CHARS`: input length limit, default `5000`

Implementation notes:

- Validates that the request does not override the configured model
- Normalizes and bounds-checks text, voice, speed, and response format
- Loads the KittenTTS model lazily and encodes output as WAV
- Caches generated audio by a SHA-256 hash of the request payload

### `whisper_service/`

Local FastAPI transcription service on `http://localhost:8100`.

- Main endpoint: `POST /v1/audio/transcriptions`
- Health endpoint: `GET /health`
- Accepts `multipart/form-data` with an uploaded audio file plus optional `model`, `language`,
  `prompt`, `task`, `response_format`, and `temperature`
- Supports `json`, `text`, and `verbose_json` responses
- Enforces a maximum upload size before writing the file to disk

Key configuration:

- `WHISPER_MODEL`: configured Whisper model name, default `turbo`
- `WHISPER_MODEL_DIR`: model cache directory
- `WHISPER_DEVICE`: `auto`, `cpu`, or `cuda`
- `MAX_UPLOAD_MB`: upload limit in megabytes, default `50`

Implementation notes:

- Validates that the request does not override the configured model
- Resolves the execution device from the configured preference and CUDA availability
- Loads Whisper lazily and removes the temporary upload file after each request
- Returns plain text, compact JSON, or verbose JSON depending on `response_format`

### `vshome/`

Go-based virtual smart home UI and control service on `http://localhost:8080`.

- Serves the browser UI from `vshome/web/`
- Loads device inventory and initial state from `devices.yaml`
- Provides a WebSocket endpoint at `ws://localhost:8080/ws`
- Provides REST endpoints for device reads and updates

Device configuration:

- Each device requires `id`, `name`, and `kind`
- Optional `room` groups devices in the frontend
- Initial device state lives under `state`
- Supported kinds: `toggle`, `sensor`, `lock`, `blind`, `vacuum`, `thermostat`,
  `humidifier`, `toaster`, and `doors`

REST and WebSocket behavior:

- `GET /api/devices` returns all devices
- `GET /api/devices/{id}` returns one device
- `PUT /api/devices/{id}` updates a device state with JSON like `{"state": {...}}`
- WebSocket clients receive an initial `state` message and later `update` messages
- Frontend updates are driven by backend messages, so UI state stays aligned with server state

Frontend notes:

- Devices are grouped by room in the dashboard
- Sliders are used for blinds, thermostat, and humidifier controls
- Switches are used for toggles, locks, doors, and the vacuum
- A static media card is included as a placeholder for the camera feed
