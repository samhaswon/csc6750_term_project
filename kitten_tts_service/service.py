"""Core runtime and cache helpers for the local KittenTTS service."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
from importlib import import_module
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
import wave

LOGGER = logging.getLogger(__name__)
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_VOICES = (
    "Bella",
    "Jasper",
    "Luna",
    "Bruno",
    "Rosie",
    "Hugo",
    "Kiki",
    "Leo",
)
SUPPORTED_RESPONSE_FORMATS = {"wav"}


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the KittenTTS service."""

    host: str
    port: int
    model_name: str
    model_dir: Path
    cache_db_path: Path
    device_preference: str
    default_voice: str
    max_input_chars: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from process environment."""

        return cls(
            host=os.environ.get("KITTEN_HOST", "0.0.0.0"),
            port=_parse_positive_int("KITTEN_PORT", 8110),
            model_name=(
                os.environ.get("KITTEN_MODEL", "KittenML/kitten-tts-nano-0.8").strip()
                or "KittenML/kitten-tts-nano-0.8"
            ),
            model_dir=Path(os.environ.get("KITTEN_MODEL_DIR", "/models/kitten_tts")),
            cache_db_path=Path(
                os.environ.get("KITTEN_CACHE_DB", "/data/kitten_tts/cache.sqlite3")
            ),
            device_preference=os.environ.get("KITTEN_DEVICE", "auto").strip().lower(),
            default_voice=os.environ.get("KITTEN_DEFAULT_VOICE", "Bella").strip() or "Bella",
            max_input_chars=_parse_positive_int("MAX_INPUT_CHARS", 5000),
        )


@dataclass(frozen=True)
class CachedAudio:
    """Cached audio payload stored in SQLite."""

    audio_data: bytes
    content_type: str
    sample_rate: int


def _parse_positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        parsed_value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed_value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed_value


def normalize_input_text(text: str, max_input_chars: int) -> str:
    """Normalize and validate user input text."""

    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("input must not be empty.")
    if len(normalized_text) > max_input_chars:
        raise ValueError(f"input exceeds the {max_input_chars} character limit.")
    return normalized_text


def validate_requested_model(requested_model: str | None, configured_model: str) -> str:
    """Ensure the request does not override the configured model."""

    if not requested_model:
        return configured_model
    normalized_request = requested_model.strip()
    if normalized_request != configured_model:
        raise ValueError(
            f"This service is configured for model '{configured_model}', not '{normalized_request}'."
        )
    return configured_model


def normalize_voice(voice: str) -> str:
    """Normalize the selected voice name."""

    normalized_voice = voice.strip()
    if not normalized_voice:
        raise ValueError("voice must not be empty.")
    if len(normalized_voice) > 64:
        raise ValueError("voice must be at most 64 characters.")
    return normalized_voice


def validate_speed(speed: float) -> float:
    """Validate the requested speech speed."""

    if speed < 0.25 or speed > 4.0:
        raise ValueError("speed must be between 0.25 and 4.0.")
    return float(speed)


def validate_response_format(response_format: str) -> str:
    """Validate the requested audio output format."""

    normalized_format = response_format.strip().lower()
    if normalized_format not in SUPPORTED_RESPONSE_FORMATS:
        raise ValueError(
            "Unsupported response_format "
            f"'{response_format}'. Supported formats: {', '.join(sorted(SUPPORTED_RESPONSE_FORMATS))}."
        )
    return normalized_format


def build_cache_key(
    *,
    model_name: str,
    input_text: str,
    voice: str,
    speed: float,
    response_format: str,
) -> str:
    """Build a stable cache key for a generation request."""

    payload = json.dumps(
        {
            "input": input_text,
            "model": model_name,
            "response_format": response_format,
            "speed": speed,
            "voice": voice,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_text(input_text: str) -> str:
    """Hash the source text without storing the raw request in SQLite."""

    return hashlib.sha256(input_text.encode("utf-8")).hexdigest()


def resolve_provider(device_preference: str, ort_module: Any | None = None) -> str:
    """Resolve the execution provider used by ONNX Runtime."""

    normalized_preference = device_preference.strip().lower()
    if normalized_preference not in {"auto", "cpu", "cuda"}:
        raise ValueError("KITTEN_DEVICE must be one of: auto, cpu, cuda.")
    if normalized_preference == "cpu":
        return "cpu"
    if ort_module is None:
        ort_module = import_module("onnxruntime")
    available_providers = set(ort_module.get_available_providers())
    has_cuda = "CUDAExecutionProvider" in available_providers
    if normalized_preference == "cuda" and not has_cuda:
        raise RuntimeError("KITTEN_DEVICE is set to cuda, but CUDAExecutionProvider is unavailable.")
    return "cuda" if has_cuda else "cpu"


def encode_wav(audio_data: Any, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    """Encode generated mono audio into a WAV payload."""

    samples = _flatten_audio_samples(audio_data)
    pcm_frames = array(
        "h",
        [
            int(max(-1.0, min(1.0, sample)) * 32767.0)
            for sample in samples
        ],
    )
    output_buffer = io.BytesIO()
    with wave.open(output_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_frames.tobytes())
    return output_buffer.getvalue()


def _flatten_audio_samples(audio_data: Any) -> list[float]:
    if hasattr(audio_data, "tolist"):
        audio_data = audio_data.tolist()
    if isinstance(audio_data, (list, tuple)) and len(audio_data) == 1 and isinstance(
        audio_data[0], (list, tuple)
    ):
        audio_data = audio_data[0]
    flat_samples: list[float] = []
    for sample in audio_data:
        if isinstance(sample, (list, tuple)):
            flat_samples.extend(float(value) for value in sample)
        else:
            flat_samples.append(float(sample))
    if not flat_samples:
        raise ValueError("Generated audio was empty.")
    return flat_samples


class CacheStore:
    """SQLite-backed generation cache."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._schema_lock = Lock()

    def initialize(self) -> None:
        """Create the cache schema if needed."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._schema_lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generated_audio (
                        cache_key TEXT PRIMARY KEY,
                        model_name TEXT NOT NULL,
                        voice TEXT NOT NULL,
                        speed REAL NOT NULL,
                        response_format TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        sample_rate INTEGER NOT NULL,
                        text_hash TEXT NOT NULL,
                        audio_data BLOB NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS generated_audio_last_accessed_idx
                    ON generated_audio (last_accessed_at)
                    """
                )

    def get(self, cache_key: str) -> CachedAudio | None:
        """Fetch a cached generation result."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT audio_data, content_type, sample_rate
                FROM generated_audio
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE generated_audio
                SET last_accessed_at = CURRENT_TIMESTAMP
                WHERE cache_key = ?
                """,
                (cache_key,),
            )
        return CachedAudio(
            audio_data=bytes(row["audio_data"]),
            content_type=str(row["content_type"]),
            sample_rate=int(row["sample_rate"]),
        )

    def put(
        self,
        *,
        cache_key: str,
        model_name: str,
        voice: str,
        speed: float,
        response_format: str,
        content_type: str,
        sample_rate: int,
        text_hash: str,
        audio_data: bytes,
    ) -> None:
        """Store a generated audio payload in the cache."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generated_audio (
                    cache_key,
                    model_name,
                    voice,
                    speed,
                    response_format,
                    content_type,
                    sample_rate,
                    text_hash,
                    audio_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    model_name = excluded.model_name,
                    voice = excluded.voice,
                    speed = excluded.speed,
                    response_format = excluded.response_format,
                    content_type = excluded.content_type,
                    sample_rate = excluded.sample_rate,
                    text_hash = excluded.text_hash,
                    audio_data = excluded.audio_data,
                    last_accessed_at = CURRENT_TIMESTAMP
                """,
                (
                    cache_key,
                    model_name,
                    voice,
                    speed,
                    response_format,
                    content_type,
                    sample_rate,
                    text_hash,
                    sqlite3.Binary(audio_data),
                ),
            )

    def stats(self) -> dict[str, int]:
        """Return simple cache statistics."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS entry_count, COALESCE(SUM(LENGTH(audio_data)), 0) AS total_bytes
                FROM generated_audio
                """
            ).fetchone()
        return {
            "entry_count": int(row["entry_count"]),
            "total_bytes": int(row["total_bytes"]),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection


class KittenTTSRuntime:
    """Lazy-loading wrapper around the KittenTTS model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._provider: str | None = None
        self._load_lock = Lock()

    @property
    def model_loaded(self) -> bool:
        """Return whether the model is already loaded."""

        return self._model is not None

    def current_provider(self) -> str:
        """Return the selected ONNX Runtime provider."""

        if self._provider is None:
            ort_module = import_module("onnxruntime")
            self._provider = resolve_provider(self.settings.device_preference, ort_module)
        return self._provider

    def load_model(self) -> Any:
        """Load the configured KittenTTS model if needed."""

        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            kittentts_module = import_module("kittentts")
            ort_module = import_module("onnxruntime")
            resolved_provider = resolve_provider(self.settings.device_preference, ort_module)
            self.settings.model_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(
                "Loading KittenTTS model '%s' with provider %s and cache dir %s",
                self.settings.model_name,
                resolved_provider,
                self.settings.model_dir,
            )
            model = kittentts_module.KittenTTS(
                self.settings.model_name,
                cache_dir=str(self.settings.model_dir),
            )
            self._configure_provider(model, ort_module, resolved_provider)
            self._model = model
            self._provider = resolved_provider
            return self._model

    def available_voices(self) -> list[str]:
        """Return the available voice names."""

        if self._model is None:
            return list(DEFAULT_VOICES)
        return list(getattr(self._model, "available_voices", DEFAULT_VOICES))

    def generate(self, input_text: str, *, voice: str, speed: float) -> Any:
        """Generate speech audio for the provided text."""

        model = self.load_model()
        available_voices = set(self.available_voices())
        if available_voices and voice not in available_voices:
            raise ValueError(
                f"Voice '{voice}' is not available. Choose from: {', '.join(sorted(available_voices))}."
            )
        return model.generate(input_text, voice=voice, speed=speed)

    @staticmethod
    def _configure_provider(model: Any, ort_module: Any, provider: str) -> None:
        inner_model = getattr(model, "model", None)
        model_path = getattr(inner_model, "model_path", None)
        if inner_model is None or not model_path:
            return
        providers = ["CPUExecutionProvider"]
        if provider == "cuda":
            providers.insert(0, "CUDAExecutionProvider")
        inner_model.session = ort_module.InferenceSession(model_path, providers=providers)
