"""FastAPI entrypoint for the local Whisper transcription service."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from whisper_service.service import (
    Settings,
    WhisperRuntime,
    build_response_payload,
    validate_requested_model,
    validate_response_format,
    validate_task,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

SETTINGS = Settings.from_env()
RUNTIME = WhisperRuntime(SETTINGS)
app = FastAPI(title="Local Whisper API", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, object]:
    """Expose runtime readiness details."""

    try:
        resolved_device = RUNTIME.current_device()
    except Exception as exc:  # pragma: no cover - defensive runtime visibility
        resolved_device = f"unavailable: {exc}"
    return {
        "status": "ok",
        "model": SETTINGS.model_name,
        "device_preference": SETTINGS.device_preference,
        "resolved_device": resolved_device,
        "model_loaded": RUNTIME.model_loaded,
    }


@app.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    model: str | None = Form(None),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    task: str = Form("transcribe"),
):
    """Accept audio input and return its transcript."""

    if not file.filename:
        raise HTTPException(status_code=400, detail="An audio file is required.")
    if temperature < 0:
        raise HTTPException(status_code=400, detail="temperature must be non-negative.")

    try:
        validate_requested_model(model, SETTINGS.model_name)
        normalized_format = validate_response_format(response_format)
        normalized_task = validate_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    suffix = Path(file.filename).suffix or ".audio"
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            await _write_upload(temp_path, file)
        result = RUNTIME.transcribe(
            temp_path,
            language=language,
            prompt=prompt,
            temperature=temperature,
            task=normalized_task,
        )
        payload = build_response_payload(result, normalized_format)
        if isinstance(payload, str):
            return PlainTextResponse(payload)
        return JSONResponse(payload)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


async def _write_upload(destination: Path, upload: UploadFile) -> None:
    bytes_written = 0
    with destination.open("wb") as output_file:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > SETTINGS.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file exceeds the {SETTINGS.max_upload_mb} MB limit.",
                )
            output_file.write(chunk)
