import base64
import tempfile
import unittest
from pathlib import Path

from deepface_service.service import DeepFaceAuthService, Settings, load_access_policy


class StubAuthService(DeepFaceAuthService):
    def __init__(self, settings: Settings, recognized_person: str | None):
        super().__init__(settings)
        self._recognized_person = recognized_person

    def recognize_person(self, frame_bytes: bytes) -> tuple[str | None, str]:
        if self._recognized_person:
            return self._recognized_person, "authorized"
        return None, "no_face_match"


class DeepFaceAuthServiceTests(unittest.TestCase):
    def test_load_access_policy_people_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "access.yaml"
            path.write_text(
                "people:\n"
                "  Alice:\n"
                "    actions:\n"
                "      - unlock_door\n"
                "      - set_thermostat\n",
                encoding="utf-8",
            )
            policy = load_access_policy(path)

        self.assertEqual(policy["alice"], {"unlock_door", "set_thermostat"})

    def test_authorize_accepts_allowed_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            access_file = data_dir / "access.yaml"
            log_file = data_dir / "auth.log"
            access_file.write_text(
                "people:\n"
                "  alice:\n"
                "    actions:\n"
                "      - unlock_door\n",
                encoding="utf-8",
            )
            settings = Settings(
                host="0.0.0.0",
                port=8120,
                data_dir=data_dir,
                access_file=access_file,
                log_file=log_file,
                model_name="Facenet512",
                detector_backend="opencv",
                enforce_detection=False,
            )
            service = StubAuthService(settings, recognized_person="alice")
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("unlock_door", frame)

            self.assertTrue(result["accepted"])
            self.assertEqual(result["decision"], "accepted")
            self.assertEqual(result["person"], "alice")
            self.assertIn("person=alice", log_file.read_text(encoding="utf-8"))
            self.assertIn("decision=accepted", log_file.read_text(encoding="utf-8"))

    def test_authorize_rejects_unknown_person(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            access_file = data_dir / "access.yaml"
            log_file = data_dir / "auth.log"
            access_file.write_text("people: {}\n", encoding="utf-8")
            settings = Settings(
                host="0.0.0.0",
                port=8120,
                data_dir=data_dir,
                access_file=access_file,
                log_file=log_file,
                model_name="Facenet512",
                detector_backend="opencv",
                enforce_detection=False,
            )
            service = StubAuthService(settings, recognized_person=None)
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("set_thermostat", frame)

            self.assertFalse(result["accepted"])
            self.assertEqual(result["decision"], "rejected")
            self.assertIsNone(result["person"])
            self.assertIn("person=unknown", log_file.read_text(encoding="utf-8"))
            self.assertIn("action=set_thermostat", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
