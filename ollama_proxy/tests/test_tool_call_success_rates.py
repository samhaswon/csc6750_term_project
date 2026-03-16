import json
import os
import unittest
from datetime import datetime, timezone
from http.client import RemoteDisconnected
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Run with: python3 -m unittest ollama_proxy.tests.test_tool_call_success_rates

"""
Last results:

model                | passed | total | success_rate
gemma3n:e2b          | 11     | 23    | 47.8%
qwen3:1.7b           | 10     | 23    | 43.5%
qwen3:0.6b           | 10     | 23    | 43.5%
qwen3.5:0.8b         |  9     | 23    | 39.1%
qwen3.5:2b           |  6     | 23    | 26.1%
functiongemma:latest | 11     | 23    | 47.8%
llama3.2:1b          | 10     | 23    | 43.5%
"""

DEFAULT_PROXY_URL = "http://localhost:8090"
DEFAULT_MODELS = [
    "gemma3n:e2b",
    "qwen3:1.7b",
    "qwen3:0.6b",
    "qwen3.5:0.8b",
    "qwen3.5:2b",
    "functiongemma:latest",
    "llama3.2:1b",
]

TEST_CASES = [
    {
        "name": "kitchen lights on",
        "prompt": "Turn on the kitchen lights.",
        "expected": {
            "action": "update",
            "id": "light_kitchen",
            "state": {"on": True},
        },
    },
    {
        "name": "kitchen lights off casual wording",
        "prompt": "Can you shut the kitchen lights off?",
        "expected": {
            "action": "update",
            "id": "light_kitchen",
            "state": {"on": False},
        },
    },
    {
        "name": "living room lights off direct id mention",
        "prompt": "Set light_living to off.",
        "expected": {
            "action": "update",
            "id": "light_living",
            "state": {"on": False},
        },
    },
    {
        "name": "start toaster",
        "prompt": "Start the toaster in the kitchen.",
        "expected": {
            "action": "update",
            "id": "toaster_home",
            "state": {"on": True},
        },
    },
    {
        "name": "stop toaster varied phrasing",
        "prompt": "Please turn the smart toaster off now.",
        "expected": {
            "action": "update",
            "id": "toaster_home",
            "state": {"on": False},
        },
    },
    {
        "name": "start vacuum",
        "prompt": "Start Broomba vacuuming.",
        "expected": {
            "action": "update",
            "id": "vacuum_broomba",
            "state": {"on": True},
        },
    },
    {
        "name": "stop vacuum alternative wording",
        "prompt": "Send the Broomba back to off.",
        "expected": {
            "action": "update",
            "id": "vacuum_broomba",
            "state": {"on": False},
        },
    },
    {
        "name": "lock front door",
        "prompt": "Lock the front door.",
        "expected": {
            "action": "update",
            "id": "door_front_lock",
            "state": {"locked": True},
        },
    },
    {
        "name": "unlock front door varied wording",
        "prompt": "Could you unlock the front door lock?",
        "expected": {
            "action": "update",
            "id": "door_front_lock",
            "state": {"locked": False},
        },
    },
    {
        "name": "open pod bay doors",
        "prompt": "Open the pod bay doors.",
        "expected": {
            "action": "update",
            "id": "pod_bay_doors",
            "state": {"open": True},
        },
    },
    {
        "name": "close pod bay doors alternate phrasing",
        "prompt": "Close the pod bay doors please.",
        "expected": {
            "action": "update",
            "id": "pod_bay_doors",
            "state": {"open": False},
        },
    },
    {
        "name": "set living blinds to 10 percent",
        "prompt": "Set the living room blinds to 10%.",
        "expected": {
            "action": "update",
            "id": "blinds_living",
            "state": {"position": 10},
        },
    },
    {
        "name": "set master blinds with natural language",
        "prompt": "Lower the master bedroom blinds to halfway.",
        "expected": {
            "action": "update",
            "id": "blinds_master",
            "state": {"position": 50},
        },
    },
    {
        "name": "set humidifier level",
        "prompt": "Set the humidifier to 65 percent.",
        "expected": {
            "action": "update",
            "id": "humidifier_home",
            "state": {"level": 65},
        },
    },
    {
        "name": "set thermostat exact value",
        "prompt": "Set the thermostat to 23 C.",
        "expected": {
            "action": "update",
            "id": "thermostat_home",
            "state": {"temperature": 23},
        },
    },
    {
        "name": "set thermostat decimal value",
        "prompt": "Make the home temperature 20.5 Celsius.",
        "expected": {
            "action": "update",
            "id": "thermostat_home",
            "state": {"temperature": 20.5},
        },
    },
    {
        "name": "read thermostat",
        "prompt": "What is the current thermostat setting?",
        "expected": {
            "action": "get",
            "id": "thermostat_home",
        },
    },
    {
        "name": "read front lock status",
        "prompt": "What's the status of the front door lock?",
        "expected": {
            "action": "get",
            "id": "door_front_lock",
        },
    },
    {
        "name": "read living blinds state",
        "prompt": "Tell me the current position of the living room blinds.",
        "expected": {
            "action": "get",
            "id": "blinds_living",
        },
    },
    {
        "name": "read kitchen lights state",
        "prompt": "Are the kitchen lights currently on or off?",
        "expected": {
            "action": "get",
            "id": "light_kitchen",
        },
    },
    {
        "name": "list devices",
        "prompt": "List all devices.",
        "expected": {
            "action": "list",
        },
    },
    {
        "name": "list devices conversational",
        "prompt": "Show me every smart home device you can control.",
        "expected": {
            "action": "list",
        },
    },
    {
        "name": "list devices concise",
        "prompt": "Give me the device inventory.",
        "expected": {
            "action": "list",
        },
    },
]


class ToolCallSuccessRateHarness(unittest.TestCase):
    maxDiff = None
    results = {}

    @staticmethod
    def _proxy_url():
        """Return proxy URL from environment or default."""
        return os.environ.get("OLLAMA_PROXY_URL", DEFAULT_PROXY_URL).rstrip("/")

    @staticmethod
    def _models():
        """Return models from environment or defaults."""
        raw_models = os.environ.get("TOOL_EVAL_MODELS", "").strip()
        if not raw_models:
            return DEFAULT_MODELS
        return [model.strip() for model in raw_models.split(",") if model.strip()]

    @staticmethod
    def _request_timeout():
        """Return API request timeout in seconds."""
        raw_timeout = os.environ.get("TOOL_EVAL_TIMEOUT", "120").strip()
        try:
            return max(int(raw_timeout), 1)
        except ValueError:
            return 120

    @classmethod
    def _post_generate(cls, prompt, model):
        """Call /api/generate for a prompt-model pair.

        :param prompt: Prompt text to send.
        :param model: Ollama model name.
        :return: Parsed response JSON.
        :raises RuntimeError: If request fails.
        """
        payload = {
            "prompt": prompt,
            "model": model,
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{cls._proxy_url()}/api/generate",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=cls._request_timeout()) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as err:
            error_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {err.code} from /api/generate for model '{model}': {error_body}"
            )
        except URLError as err:
            raise RuntimeError(
                f"Could not reach {cls._proxy_url()} for model '{model}': {err.reason}"
            )
        except RemoteDisconnected as err:
            raise RuntimeError(
                f"Connection dropped from /api/generate for model '{model}': {err}"
            )
        except (TimeoutError, SocketTimeout) as err:
            raise RuntimeError(
                f"Timed out calling /api/generate for model '{model}': {err}"
            )

    @classmethod
    def _post_tool_action(cls, payload):
        """Call /tools/smart_home with a direct tool payload.

        :param payload: Tool payload containing action and related fields.
        :return: Parsed response payload.
        :raises RuntimeError: If request fails.
        """
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{cls._proxy_url()}/tools/smart_home",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=cls._request_timeout()) as response:
                return response.getcode(), json.loads(response.read().decode("utf-8"))
        except HTTPError as err:
            error_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {err.code} from /tools/smart_home: {error_body}"
            )
        except URLError as err:
            raise RuntimeError(
                f"Could not reach {cls._proxy_url()} /tools/smart_home: {err.reason}"
            )
        except RemoteDisconnected as err:
            raise RuntimeError(
                f"Connection dropped from /tools/smart_home: {err}"
            )
        except (TimeoutError, SocketTimeout) as err:
            raise RuntimeError(
                f"Timed out calling /tools/smart_home: {err}"
            )

    @staticmethod
    def _is_expected_tool_call(tool_call, expected):
        """Validate tool call output against an expected shape."""
        if not isinstance(tool_call, dict):
            return False
        if tool_call.get("action") != expected.get("action"):
            return False
        if "id" in expected and tool_call.get("id") != expected["id"]:
            return False
        expected_state = expected.get("state")
        if expected_state is None:
            return True
        state = tool_call.get("state")
        if not isinstance(state, dict):
            return False
        for key, expected_value in expected_state.items():
            if state.get(key) != expected_value:
                return False
        return True

    @classmethod
    def _prepare_case_state(cls, expected):
        """Set a deterministic baseline for update cases.

        :param expected: Expected action payload for the case.
        """
        if expected.get("action") != "update":
            return
        device_id = expected.get("id")
        target_state = expected.get("state")
        if not device_id or not isinstance(target_state, dict) or not target_state:
            return
        key, value = next(iter(target_state.items()))
        baseline_state = {}
        if isinstance(value, bool):
            baseline_state[key] = not value
        elif isinstance(value, (int, float)):
            if key in ("position", "level"):
                baseline_state[key] = 0 if value != 0 else 100
            elif key == "temperature":
                baseline_state[key] = value - 2 if value > -20 else value + 2
            else:
                baseline_state[key] = value
        else:
            return
        cls._post_tool_action(
            {
                "action": "update",
                "id": device_id,
                "state": baseline_state,
            }
        )

    @classmethod
    def _is_expected_action_performed(cls, expected, response):
        """Validate that the intended action was actually executed.

        :param expected: Expected tool behavior.
        :param response: Parsed /api/generate response.
        :return: Tuple of (matched, details).
        """
        tool_result = response.get("tool_result")
        action = expected.get("action")
        if action == "list":
            if not isinstance(tool_result, dict):
                return False, "missing tool_result"
            data = tool_result.get("data")
            if tool_result.get("status") != 200 or not isinstance(data, list):
                return False, "list action not executed"
            return True, None
        if action == "get":
            if not isinstance(tool_result, dict):
                return False, "missing tool_result"
            data = tool_result.get("data")
            if tool_result.get("status") != 200 or not isinstance(data, dict):
                return False, "get action not executed"
            if data.get("id") != expected.get("id"):
                return False, "get returned wrong device"
            return True, None
        if action != "update":
            return False, "unsupported expected action"
        if not isinstance(tool_result, dict):
            return False, "missing tool_result"
        data = tool_result.get("data")
        if tool_result.get("status") != 200 or not isinstance(data, dict):
            return False, "update action not executed"
        if data.get("id") != expected.get("id"):
            return False, "updated wrong device"
        expected_state = expected.get("state", {})
        current_state = data.get("state", {})
        for key, expected_value in expected_state.items():
            if current_state.get(key) != expected_value:
                return False, f"update result state mismatch for '{key}'"
        get_status, get_data = cls._post_tool_action(
            {
                "action": "get",
                "id": expected.get("id"),
            }
        )
        if get_status != 200 or not isinstance(get_data, dict):
            return False, "could not verify final device state"
        final_state = get_data.get("state", {})
        for key, expected_value in expected_state.items():
            if final_state.get(key) != expected_value:
                return False, f"final state mismatch for '{key}'"
        return True, None

    @classmethod
    def _evaluate_model(cls, model):
        """Run all test cases for one model and return scored results."""
        case_results = []
        for case in TEST_CASES:
            response = {}
            tool_call = None
            error = None
            action_error = None
            action_matched = False
            try:
                cls._prepare_case_state(case["expected"])
                response = cls._post_generate(case["prompt"], model)
                tool_call = response.get("tool_call")
                matched = cls._is_expected_tool_call(tool_call, case["expected"])
                action_matched, action_error = cls._is_expected_action_performed(
                    case["expected"], response
                )
            except Exception as err:
                matched = False
                action_matched = False
                error = str(err)
            passed = matched and action_matched and error is None and action_error is None
            case_results.append(
                {
                    "name": case["name"],
                    "prompt": case["prompt"],
                    "expected": case["expected"],
                    "tool_call": tool_call,
                    "tool_result": response.get("tool_result"),
                    "response": response.get("response"),
                    "tool_call_matched": matched,
                    "action_matched": action_matched,
                    "matched": passed,
                    "action_error": action_error,
                    "error": error,
                }
            )
        total = len(case_results)
        passed = sum(1 for item in case_results if item["matched"])
        return {
            "model": model,
            "passed": passed,
            "total": total,
            "success_rate": (passed / total) if total else 0.0,
            "cases": case_results,
        }

    @classmethod
    def _write_artifact(cls):
        """Write model evaluation summary and case details to a JSON artifact."""
        artifact_dir = Path(__file__).resolve().parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "tool_call_success_rates.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "proxy_url": cls._proxy_url(),
            "models": cls._models(),
            "results": cls.results,
        }
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return artifact_path

    @classmethod
    def _print_summary(cls):
        """Print a compact success-rate summary table for quick comparison."""
        print("\nTool-call success rates:")
        print("model | passed | total | success_rate")
        for model in cls._models():
            result = cls.results.get(model)
            if not result:
                continue
            rate = f"{result['success_rate'] * 100:.1f}%"
            print(f"{model} | {result['passed']} | {result['total']} | {rate}")

    def test_model_success_rates(self):
        """Evaluate tool-call success rates across configured models."""
        if os.environ.get("TOOL_EVAL_SKIP", "").strip() == "1":
            self.skipTest("TOOL_EVAL_SKIP=1")

        models = self._models()
        self.assertGreater(len(models), 0, "No models configured")

        for model in models:
            self.results[model] = self._evaluate_model(model)

        artifact_path = self._write_artifact()
        self._print_summary()
        print(f"Detailed artifact: {artifact_path}")


if __name__ == "__main__":
    unittest.main()
