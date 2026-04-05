import unittest
from unittest.mock import patch

from ollama_proxy.main import resolve_model_name


class ModelResolutionTests(unittest.TestCase):
    @patch("ollama_proxy.main.list_ollama_models", return_value=["gemma4:e2b", "qwen3:1.7b"])
    def test_exact_match(self, _):
        resolved, available = resolve_model_name("gemma4:e2b")
        self.assertEqual(resolved, "gemma4:e2b")
        self.assertEqual(available, ["gemma4:e2b", "qwen3:1.7b"])

    @patch("ollama_proxy.main.list_ollama_models", return_value=["gemma4:e2b"])
    def test_trims_model_name(self, _):
        resolved, _available = resolve_model_name("  gemma4:e2b  ")
        self.assertEqual(resolved, "gemma4:e2b")

    @patch("ollama_proxy.main.list_ollama_models", return_value=["gemma4:e2b"])
    def test_no_base_name_fallback_by_default(self, _):
        resolved, _available = resolve_model_name("gemma4:missing-tag")
        self.assertEqual(resolved, "gemma4:missing-tag")

    @patch("ollama_proxy.main.ALLOW_MODEL_FAMILY_FALLBACK", True)
    @patch("ollama_proxy.main.list_ollama_models", return_value=["gemma4:e2b"])
    def test_base_name_fallback_when_enabled(self, _models):
        resolved, _available = resolve_model_name("gemma4:missing-tag")
        self.assertEqual(resolved, "gemma4:e2b")


if __name__ == "__main__":
    unittest.main()
