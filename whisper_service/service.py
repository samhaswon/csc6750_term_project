"""Core runtime helpers for the local Whisper transcription service."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

LOGGER = logging.getLogger(__name__)
SUPPORTED_RESPONSE_FORMATS = {"json", "text", "verbose_json"}
SUPPORTED_TASKS = {"transcribe", "translate"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the Whisper service."""

    host: str
    port: int
    model_name: str
    model_dir: Path
    device_preference: str
    max_upload_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from process environment."""

        return cls(
            host=os.environ.get("WHISPER_HOST", "0.0.0.0"),
            port=_parse_positive_int("WHISPER_PORT", 8100),
            model_name=os.environ.get("WHISPER_MODEL", "turbo").strip() or "turbo",
            model_dir=Path(os.environ.get("WHISPER_MODEL_DIR", "/models/whisper")),
            device_preference=os.environ.get("WHISPER_DEVICE", "auto").strip().lower(),
            max_upload_mb=_parse_positive_int("MAX_UPLOAD_MB", 50),
        )

    @property
    def max_upload_bytes(self) -> int:
        """Return the upload limit in bytes."""

        return self.max_upload_mb * 1024 * 1024


def _parse_positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed_value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed_value


def validate_requested_model(requested_model: str | None, configured_model: str) -> str:
    """Ensure the request does not override the configured local model."""

    if not requested_model:
        return configured_model
    normalized_request = requested_model.strip()
    if normalized_request != configured_model:
        raise ValueError(
            f"This service is configured for model '{configured_model}', not '{normalized_request}'."
        )
    return configured_model


def validate_task(task: str) -> str:
    """Validate the requested Whisper task."""

    normalized_task = task.strip().lower()
    if normalized_task not in SUPPORTED_TASKS:
        raise ValueError(
            f"Unsupported task '{task}'. Supported tasks: {', '.join(sorted(SUPPORTED_TASKS))}."
        )
    return normalized_task


def validate_response_format(response_format: str) -> str:
    """Validate the requested response format."""

    normalized_format = response_format.strip().lower()
    if normalized_format not in SUPPORTED_RESPONSE_FORMATS:
        raise ValueError(
            "Unsupported response_format "
            f"'{response_format}'. Supported formats: {', '.join(sorted(SUPPORTED_RESPONSE_FORMATS))}."
        )
    return normalized_format


def resolve_device(device_preference: str, torch_module: Any | None = None) -> str:
    """Resolve the actual inference device to use."""

    normalized_preference = device_preference.strip().lower()
    if normalized_preference not in {"auto", "cpu", "cuda"}:
        raise ValueError("WHISPER_DEVICE must be one of: auto, cpu, cuda.")
    if normalized_preference == "cpu":
        return "cpu"
    if torch_module is None:
        torch_module = import_module("torch")
    has_cuda = bool(torch_module.cuda.is_available())
    if normalized_preference == "cuda" and not has_cuda:
        raise RuntimeError("WHISPER_DEVICE is set to cuda, but CUDA is not available.")
    return "cuda" if has_cuda else "cpu"


def build_response_payload(result: dict[str, Any], response_format: str) -> str | dict[str, Any]:
    """Translate a Whisper result into an API payload."""

    normalized_format = validate_response_format(response_format)
    transcript_text = str(result.get("text", "")).strip()
    if normalized_format == "text":
        return transcript_text
    if normalized_format == "verbose_json":
        segments = [_normalize_segment(segment) for segment in result.get("segments", [])]
        return {
            "text": transcript_text,
            "language": result.get("language"),
            "duration": _calculate_duration(segments),
            "segments": segments,
        }
    return {"text": transcript_text}


def _normalize_segment(segment: dict[str, Any]) -> dict[str, Any]:
    normalized_segment = {
        "id": segment.get("id"),
        "start": segment.get("start"),
        "end": segment.get("end"),
        "text": segment.get("text", ""),
    }
    if "seek" in segment:
        normalized_segment["seek"] = segment["seek"]
    if "tokens" in segment:
        normalized_segment["tokens"] = segment["tokens"]
    if "temperature" in segment:
        normalized_segment["temperature"] = segment["temperature"]
    if "avg_logprob" in segment:
        normalized_segment["avg_logprob"] = segment["avg_logprob"]
    if "compression_ratio" in segment:
        normalized_segment["compression_ratio"] = segment["compression_ratio"]
    if "no_speech_prob" in segment:
        normalized_segment["no_speech_prob"] = segment["no_speech_prob"]
    return normalized_segment


def _calculate_duration(segments: list[dict[str, Any]]) -> float | None:
    if not segments:
        return None
    end_values = [segment.get("end") for segment in segments if isinstance(segment.get("end"), (int, float))]
    if not end_values:
        return None
    return float(max(end_values))


class WhisperRuntime:
    """Lazy-loading wrapper around the OpenAI Whisper model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._device: str | None = None
        self._load_lock = Lock()

    @property
    def model_loaded(self) -> bool:
        """Return whether the Whisper model has already been loaded."""

        return self._model is not None

    def current_device(self) -> str:
        """Return the selected execution device."""

        if self._device is None:
            self._device = resolve_device(self.settings.device_preference)
        return self._device

    def load_model(self) -> Any:
        """Load the configured Whisper model if needed."""

        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            whisper_module = import_module("whisper")
            resolved_device = self.current_device()
            self.settings.model_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(
                "Loading Whisper model '%s' on %s with cache dir %s",
                self.settings.model_name,
                resolved_device,
                self.settings.model_dir,
            )
            self._model = whisper_module.load_model(
                self.settings.model_name,
                device=resolved_device,
                download_root=str(self.settings.model_dir),
            )
            return self._model

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        prompt: str | None = None,
        temperature: float = 0.0,
        task: str = "transcribe",
    ) -> dict[str, Any]:
        """Run a Whisper transcription job for the provided file."""

        normalized_task = validate_task(task)
        model = self.load_model()
        transcription_options: dict[str, Any] = {
            "verbose": False,
            "task": normalized_task,
            "temperature": temperature,
            "fp16": self.current_device() == "cuda",
        }
        if language:
            transcription_options["language"] = language.strip()
        if prompt:
            transcription_options["initial_prompt"] = prompt.strip()
        return model.transcribe(str(audio_path), **transcription_options)
