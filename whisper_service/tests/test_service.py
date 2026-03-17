"""Unit tests for the Whisper service helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from whisper_service.service import (
    Settings,
    WhisperRuntime,
    build_response_payload,
    resolve_device,
    validate_requested_model,
    validate_response_format,
    validate_task,
)


class ResolveDeviceTests(unittest.TestCase):
    def test_auto_uses_cuda_when_available(self) -> None:
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: True)
        )
        self.assertEqual(resolve_device("auto", fake_torch), "cuda")

    def test_auto_uses_cpu_when_cuda_missing(self) -> None:
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False)
        )
        self.assertEqual(resolve_device("auto", fake_torch), "cpu")

    def test_explicit_cuda_requires_cuda(self) -> None:
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False)
        )
        with self.assertRaises(RuntimeError):
            resolve_device("cuda", fake_torch)


class ValidationTests(unittest.TestCase):
    def test_requested_model_must_match_configured_model(self) -> None:
        self.assertEqual(validate_requested_model(None, "turbo"), "turbo")
        self.assertEqual(validate_requested_model("turbo", "turbo"), "turbo")
        with self.assertRaises(ValueError):
            validate_requested_model("small", "turbo")

    def test_task_validation_rejects_unknown_values(self) -> None:
        self.assertEqual(validate_task("transcribe"), "transcribe")
        with self.assertRaises(ValueError):
            validate_task("summarize")

    def test_response_format_validation_rejects_unknown_values(self) -> None:
        self.assertEqual(validate_response_format("json"), "json")
        with self.assertRaises(ValueError):
            validate_response_format("srt")


class ResponsePayloadTests(unittest.TestCase):
    def test_verbose_json_includes_segments_and_duration(self) -> None:
        payload = build_response_payload(
            {
                "text": "hello world",
                "language": "en",
                "segments": [
                    {"id": 0, "start": 0.0, "end": 1.5, "text": "hello "},
                    {"id": 1, "start": 1.5, "end": 3.0, "text": "world"},
                ],
            },
            "verbose_json",
        )
        self.assertEqual(payload["text"], "hello world")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["duration"], 3.0)
        self.assertEqual(len(payload["segments"]), 2)

    def test_text_response_returns_plain_string(self) -> None:
        payload = build_response_payload({"text": " hello "}, "text")
        self.assertEqual(payload, "hello")


class WhisperRuntimeTests(unittest.TestCase):
    def test_transcribe_uses_initial_prompt_and_fp16_for_cuda(self) -> None:
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = {"text": "done"}

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                host="0.0.0.0",
                port=8100,
                model_name="turbo",
                model_dir=Path(temp_dir),
                device_preference="auto",
                max_upload_mb=10,
            )
            runtime = WhisperRuntime(settings)

            fake_whisper = types.SimpleNamespace(load_model=mock.Mock(return_value=fake_model))
            fake_torch = types.SimpleNamespace(
                cuda=types.SimpleNamespace(is_available=lambda: True)
            )

            def fake_import(name: str):
                if name == "torch":
                    return fake_torch
                if name == "whisper":
                    return fake_whisper
                raise AssertionError(name)

            with mock.patch("whisper_service.service.import_module", side_effect=fake_import):
                result = runtime.transcribe(
                    Path(temp_dir) / "audio.wav",
                    language="en",
                    prompt="Product names",
                    temperature=0.2,
                    task="transcribe",
                )

        self.assertEqual(result, {"text": "done"})
        fake_whisper.load_model.assert_called_once_with(
            "turbo",
            device="cuda",
            download_root=temp_dir,
        )
        fake_model.transcribe.assert_called_once_with(
            str(Path(temp_dir) / "audio.wav"),
            verbose=False,
            task="transcribe",
            temperature=0.2,
            fp16=True,
            language="en",
            initial_prompt="Product names",
        )


if __name__ == "__main__":
    unittest.main()
