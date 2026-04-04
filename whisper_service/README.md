# Whisper Service

Local HTTP service for OpenAI Whisper transcription.

Might port this to a faster version in the future: https://github.com/SYSTRAN/faster-whisper

## Endpoint

- `POST /v1/audio/transcriptions`
- `GET /health`

`/v1/audio/transcriptions` accepts `multipart/form-data` with:

- `file`: required audio upload
- `model`: optional, must match `WHISPER_MODEL` when provided
- `language`: optional language code
- `prompt`: optional transcription prompt
- `task`: `transcribe` or `translate`
- `response_format`: `json`, `text`, or `verbose_json`
- `temperature`: optional non-negative float

Example:

```bash
curl -X POST http://localhost:8100/v1/audio/transcriptions \
  -F "file=@sample.wav" \
  -F "response_format=json"
```

Example response:

```json
{
  "text": "Hello from Whisper."
}
```

## Environment

- `WHISPER_MODEL`: model name to load, defaults to `turbo`
- `WHISPER_MODEL_DIR`: cache directory for downloaded model weights
- `WHISPER_DEVICE`: `auto`, `cpu`, or `cuda`
- `MAX_UPLOAD_MB`: upload size limit, defaults to `50`

The container uses a CUDA-enabled PyTorch build and will select the GPU automatically when
Docker exposes one to the container.
If you want GPU inference, the Docker host still needs NVIDIA Container Toolkit support.
