"""Unit tests for the KittenTTS service helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from kitten_tts_service.service import (
    CacheStore,
    KittenTTSRuntime,
    Settings,
    build_cache_key,
    encode_wav,
    normalize_input_text,
    resolve_provider,
    validate_requested_model,
    validate_response_format,
    validate_speed,
)


class ValidationTests(unittest.TestCase):
    def test_requested_model_must_match(self) -> None:
        self.assertEqual(
            validate_requested_model(None, "KittenML/kitten-tts-nano-0.8"),
            "KittenML/kitten-tts-nano-0.8",
        )
        with self.assertRaises(ValueError):
            validate_requested_model(
                "KittenML/kitten-tts-mini-0.8",
                "KittenML/kitten-tts-nano-0.8",
            )

    def test_input_validation_strips_whitespace_and_checks_length(self) -> None:
        self.assertEqual(normalize_input_text("  hello  ", 20), "hello")
        with self.assertRaises(ValueError):
            normalize_input_text("   ", 20)
        with self.assertRaises(ValueError):
            normalize_input_text("abc", 2)

    def test_speed_and_format_validation(self) -> None:
        self.assertEqual(validate_speed(1.5), 1.5)
        self.assertEqual(validate_response_format("wav"), "wav")
        with self.assertRaises(ValueError):
            validate_speed(10)
        with self.assertRaises(ValueError):
            validate_response_format("mp3")


class CacheKeyTests(unittest.TestCase):
    def test_cache_key_is_deterministic_and_changes_with_input(self) -> None:
        first_key = build_cache_key(
            model_name="KittenML/kitten-tts-nano-0.8",
            input_text="hello",
            voice="Bella",
            speed=1.0,
            response_format="wav",
        )
        second_key = build_cache_key(
            model_name="KittenML/kitten-tts-nano-0.8",
            input_text="hello",
            voice="Bella",
            speed=1.0,
            response_format="wav",
        )
        different_key = build_cache_key(
            model_name="KittenML/kitten-tts-nano-0.8",
            input_text="hello again",
            voice="Bella",
            speed=1.0,
            response_format="wav",
        )
        self.assertEqual(first_key, second_key)
        self.assertNotEqual(first_key, different_key)


class ProviderTests(unittest.TestCase):
    def test_auto_uses_cuda_when_available(self) -> None:
        fake_ort = types.SimpleNamespace(
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        self.assertEqual(resolve_provider("auto", fake_ort), "cuda")

    def test_auto_falls_back_to_cpu(self) -> None:
        fake_ort = types.SimpleNamespace(
            get_available_providers=lambda: ["CPUExecutionProvider"]
        )
        self.assertEqual(resolve_provider("auto", fake_ort), "cpu")

    def test_explicit_cuda_requires_provider(self) -> None:
        fake_ort = types.SimpleNamespace(
            get_available_providers=lambda: ["CPUExecutionProvider"]
        )
        with self.assertRaises(RuntimeError):
            resolve_provider("cuda", fake_ort)


class CacheStoreTests(unittest.TestCase):
    def test_cache_round_trip_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CacheStore(Path(temp_dir) / "cache.sqlite3")
            store.initialize()
            store.put(
                cache_key="abc",
                model_name="model'); DROP TABLE generated_audio; --",
                voice="Bella",
                speed=1.0,
                response_format="wav",
                content_type="audio/wav",
                sample_rate=24000,
                text_hash="hash",
                audio_data=b"audio",
            )
            cached = store.get("abc")
            stats = store.stats()

        self.assertIsNotNone(cached)
        self.assertEqual(cached.audio_data, b"audio")
        self.assertEqual(stats["entry_count"], 1)
        self.assertGreaterEqual(stats["total_bytes"], 5)


class RuntimeTests(unittest.TestCase):
    def test_runtime_loads_model_and_reconfigures_provider(self) -> None:
        fake_inner_model = types.SimpleNamespace(model_path="/tmp/model.onnx")
        fake_model = types.SimpleNamespace(
            model=fake_inner_model,
            available_voices=["Bella", "Jasper"],
            generate=mock.Mock(return_value=[0.0, 0.25, -0.25]),
        )
        fake_kittentts = types.SimpleNamespace(KittenTTS=mock.Mock(return_value=fake_model))
        fake_ort = types.SimpleNamespace(
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
            InferenceSession=mock.Mock(return_value="cuda-session"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                host="0.0.0.0",
                port=8110,
                model_name="KittenML/kitten-tts-nano-0.8",
                model_dir=Path(temp_dir),
                cache_db_path=Path(temp_dir) / "cache.sqlite3",
                device_preference="auto",
                default_voice="Bella",
                max_input_chars=5000,
            )
            runtime = KittenTTSRuntime(settings)

            def fake_import(name: str):
                if name == "kittentts":
                    return fake_kittentts
                if name == "onnxruntime":
                    return fake_ort
                raise AssertionError(name)

            with mock.patch("kitten_tts_service.service.import_module", side_effect=fake_import):
                audio = runtime.generate("hello", voice="Bella", speed=1.0)

        self.assertEqual(audio, [0.0, 0.25, -0.25])
        fake_kittentts.KittenTTS.assert_called_once_with(
            "KittenML/kitten-tts-nano-0.8",
            cache_dir=temp_dir,
        )
        fake_ort.InferenceSession.assert_called_once_with(
            "/tmp/model.onnx",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        fake_model.generate.assert_called_once_with("hello", voice="Bella", speed=1.0)


class EncodingTests(unittest.TestCase):
    def test_encode_wav_returns_wav_bytes(self) -> None:
        wav_bytes = encode_wav([0.0, 0.25, -0.25])
        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav_bytes[:16])


if __name__ == "__main__":
    unittest.main()
