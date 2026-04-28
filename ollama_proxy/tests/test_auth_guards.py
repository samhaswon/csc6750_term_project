import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import json

from ollama_proxy.main import (
    authorize_sensitive_action,
    determine_protected_action,
    execute_tool_call,
)


class AuthGuardTests(unittest.TestCase):
    def test_determine_protected_action_unlock_door(self):
        device = {"kind": "lock", "id": "door_front_lock"}
        self.assertEqual(determine_protected_action(device, {"locked": False}), "unlock_door")

    def test_determine_protected_action_open_garage(self):
        device = {"kind": "doors", "id": "garage_door"}
        self.assertEqual(determine_protected_action(device, {"open": True}), "open_garage")

    def test_determine_protected_action_set_thermostat(self):
        device = {"kind": "thermostat", "id": "thermostat_home"}
        self.assertEqual(
            determine_protected_action(device, {"temperature": 22}),
            "set_thermostat",
        )

    def test_determine_protected_action_not_protected(self):
        device = {"kind": "toggle", "id": "light_kitchen"}
        self.assertIsNone(determine_protected_action(device, {"on": True}))

    @patch("ollama_proxy.main.AUTH_ENABLED", True)
    @patch("ollama_proxy.main.authorize_sensitive_action")
    @patch("ollama_proxy.main.forward_request")
    def test_execute_tool_call_rejects_when_auth_fails(self, mock_forward, mock_auth):
        mock_forward.side_effect = [
            (200, {"id": "door_front_lock", "kind": "lock", "state": {"locked": True}}),
        ]
        mock_auth.return_value = {
            "accepted": False,
            "decision": "rejected",
            "person": None,
            "desired_action": "unlock_door",
            "reason": "no_face_match",
        }

        result = execute_tool_call(
            {"action": "update", "id": "door_front_lock", "state": {"locked": False}}
        )

        self.assertEqual(result["status"], 403)
        self.assertIn("authorization rejected", result["data"]["error"])
        self.assertEqual(result["data"]["auth"]["decision"], "rejected")

    @patch("ollama_proxy.main.AUTH_ENABLED", True)
    @patch("ollama_proxy.main.authorize_sensitive_action")
    @patch("ollama_proxy.main.forward_request")
    def test_execute_tool_call_allows_when_auth_passes(self, mock_forward, mock_auth):
        mock_forward.side_effect = [
            (200, {"id": "door_front_lock", "kind": "lock", "state": {"locked": True}}),
            (200, {"id": "door_front_lock", "kind": "lock", "state": {"locked": False}}),
        ]
        mock_auth.return_value = {
            "accepted": True,
            "decision": "accepted",
            "person": "alice",
            "desired_action": "unlock_door",
            "reason": "authorized",
        }

        result = execute_tool_call(
            {"action": "update", "id": "door_front_lock", "state": {"locked": False}}
        )

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["auth"]["person"], "alice")

    @patch("ollama_proxy.main.capture_webcam_frame_base64")
    @patch("ollama_proxy.main.DEEPFACE_AUTH_KEY", "test-key")
    @patch("ollama_proxy.main.urlopen")
    def test_authorize_sensitive_action_includes_auth_key(
        self,
        mock_urlopen,
        mock_capture,
    ):
        class StubResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"accepted": true, "decision": "accepted", "person": "default"}'

        mock_capture.return_value = ("ZmFrZS1mcmFtZQ==", None)
        mock_urlopen.return_value = StubResponse()

        authorize_sensitive_action("unlock_door")

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["auth_key"], "test-key")
        self.assertEqual(payload["desired_action"], "unlock_door")
        self.assertIn("frame_jpeg_base64", payload)

    @patch("ollama_proxy.main.capture_webcam_frame_base64")
    @patch("ollama_proxy.main.urlopen")
    def test_authorize_sensitive_action_sanitizes_http_error_payload(
        self, mock_urlopen, mock_capture
    ):
        import io

        mock_capture.return_value = ("ZmFrZS1mcmFtZQ==", None)
        mock_urlopen.side_effect = HTTPError(
            url="http://deepface_service:8120/auth/authorize",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(
                b'{"detail":"You have tensorflow 2.21.0 and this requires tf-keras package."}'
            ),
        )

        result = authorize_sensitive_action("unlock_door")

        self.assertFalse(result["accepted"])
        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(
            result["reason"],
            "You have tensorflow 2.21.0 and this requires tf-keras package.",
        )


if __name__ == "__main__":
    unittest.main()
