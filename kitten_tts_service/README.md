# KittenTTS Service

Local HTTP service for KittenTTS speech generation with a SQLite-backed generation cache.

## Endpoints

- `POST /v1/audio/speech`
- `GET /health`

`/v1/audio/speech` accepts JSON with:

- `input`: required text to synthesize
- `model`: optional, must match `KITTEN_MODEL` when provided
- `voice`: optional, defaults to `KITTEN_DEFAULT_VOICE`
- `speed`: optional float from `0.25` to `4.0`
- `response_format`: currently `wav`

Example:

```bash
curl -X POST http://localhost:8110/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello from KittenTTS.",
    "voice": "Bella",
    "response_format": "wav"
  }' \
  --output speech.wav
```

The service returns audio directly and includes `X-Cache-Hit: 1` when the request was served
from the SQLite cache.

## Environment

- `KITTEN_MODEL`: model name to load, defaults to `KittenML/kitten-tts-nano-0.8`
- `KITTEN_MODEL_DIR`: Hugging Face asset cache directory
- `KITTEN_CACHE_DB`: SQLite database path for generated audio cache
- `KITTEN_DEVICE`: `auto`, `cpu`, or `cuda`
- `KITTEN_DEFAULT_VOICE`: default voice, defaults to `Bella`
- `MAX_INPUT_CHARS`: maximum input size, defaults to `5000`

The cache stores parameterized SQLite records keyed by a SHA-256 hash of the request payload, so
identical requests reuse the same generated audio instead of re-running synthesis.
