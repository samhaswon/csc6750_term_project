# CSC6750 Term Project

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
- Tool bridge endpoint: `POST /tools/smart_home` (see `ollama_proxy/README.md`).
- The Whisper service runs on `http://localhost:8100`.
- Health check: `GET /health`
- Transcription endpoint: `POST /v1/audio/transcriptions` (see `whisper_service/README.md`).
- The KittenTTS service runs on `http://localhost:8110`.
- Health check: `GET /health`
- Speech endpoint: `POST /v1/audio/speech` (see `kitten_tts_service/README.md`).
