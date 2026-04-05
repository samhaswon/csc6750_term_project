"""FastAPI entrypoint for the local KittenTTS service."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kitten_tts_service.service import (
    CacheStore,
    KittenTTSRuntime,
    Settings,
    build_cache_key,
    encode_wav,
    hash_text,
    normalize_input_text,
    normalize_voice,
    validate_requested_model,
    validate_response_format,
    validate_speed,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    """Request model for text-to-speech synthesis."""

    model: str | None = None
    input: str = Field(..., min_length=1)
    voice: str | None = None
    response_format: str = "wav"
    speed: float = 1.0


SETTINGS = Settings.from_env()
CACHE = CacheStore(SETTINGS.cache_db_path)
CACHE.initialize()
RUNTIME = KittenTTSRuntime(SETTINGS)
app = FastAPI(title="Local KittenTTS API", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, object]:
    """Expose runtime and cache readiness details."""

    cache_stats = CACHE.stats()
    try:
        resolved_provider = RUNTIME.current_provider()
    except Exception as exc:  # pragma: no cover - defensive runtime visibility
        resolved_provider = f"unavailable: {exc}"
    return {
        "status": "ok",
        "model": SETTINGS.model_name,
        "default_voice": SETTINGS.default_voice,
        "device_preference": SETTINGS.device_preference,
        "resolved_provider": resolved_provider,
        "model_loaded": RUNTIME.model_loaded,
        "cache_entries": cache_stats["entry_count"],
        "cache_bytes": cache_stats["total_bytes"],
    }


@app.post("/v1/audio/speech")
async def create_speech(payload: SpeechRequest) -> Response:
    """Generate audio from text using KittenTTS."""

    try:
        configured_model = validate_requested_model(payload.model, SETTINGS.model_name)
        input_text = normalize_input_text(payload.input, SETTINGS.max_input_chars)
        voice = normalize_voice(payload.voice or SETTINGS.default_voice)
        response_format = validate_response_format(payload.response_format)
        speed = validate_speed(payload.speed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cache_key = build_cache_key(
        model_name=configured_model,
        input_text=input_text,
        voice=voice,
        speed=speed,
        response_format=response_format,
    )
    try:
        cached_audio = CACHE.get(cache_key)
    except Exception as exc:
        LOGGER.exception(
            "KittenTTS cache read failed model=%s voice=%s speed=%.2f chars=%d",
            configured_model,
            voice,
            speed,
            len(input_text),
        )
        raise HTTPException(status_code=500, detail=f"Cache read failed: {exc}") from exc
    if cached_audio is not None:
        return Response(
            content=cached_audio.audio_data,
            media_type=cached_audio.content_type,
            headers={"X-Cache-Hit": "1"},
        )

    try:
        audio_data = RUNTIME.generate(input_text, voice=voice, speed=speed)
        response_body = encode_wav(audio_data)
        CACHE.put(
            cache_key=cache_key,
            model_name=configured_model,
            voice=voice,
            speed=speed,
            response_format=response_format,
            content_type="audio/wav",
            sample_rate=24000,
            text_hash=hash_text(input_text),
            audio_data=response_body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        LOGGER.exception(
            "KittenTTS runtime error model=%s voice=%s speed=%.2f chars=%d",
            configured_model,
            voice,
            speed,
            len(input_text),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception(
            "KittenTTS generation failed model=%s voice=%s speed=%.2f chars=%d",
            configured_model,
            voice,
            speed,
            len(input_text),
        )
        raise HTTPException(status_code=500, detail=f"Speech generation failed: {exc}") from exc

    return Response(
        content=response_body,
        media_type="audio/wav",
        headers={"X-Cache-Hit": "0"},
    )
