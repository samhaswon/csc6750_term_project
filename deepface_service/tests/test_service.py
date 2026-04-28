import base64
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deepface_service.service import (
    DEFAULT_MYSQL_USER_ID,
    DEFAULT_MYSQL_USERNAME,
    DeepFaceAuthService,
    FaceRecord,
    MySQLSettings,
    Settings,
    UserRecord,
    _collect_default_user_actions,
    _load_face_entries,
    load_access_policy,
)


class StubAuthRepository:
    def __init__(
        self,
        user_record: UserRecord | None = None,
        allowed_actions: set[str] | None = None,
        face_records: list[FaceRecord] | None = None,
    ):
        self.user_record = user_record
        self.allowed_actions = allowed_actions or set()
        self.face_records = face_records or []
        self.events = []

    def get_user_by_key(self, auth_key: str) -> UserRecord | None:
        if self.user_record and auth_key == self.user_record.key:
            return self.user_record
        return None

    def get_face_records(self, user_id: str) -> list[FaceRecord]:
        if self.user_record and user_id == self.user_record.user_id:
            return list(self.face_records)
        return []

    def get_allowed_actions(self, user_id: str) -> set[str]:
        if self.user_record and user_id == self.user_record.user_id:
            return set(self.allowed_actions)
        return set()

    def log_auth_event(
        self,
        timestamp: dt.datetime,
        user_id: str | None,
        person_identification: str,
        desired_action: str,
        decision: str,
        reason: str,
    ) -> None:
        self.events.append(
            {
                "timestamp": timestamp,
                "user_id": user_id,
                "person_identification": person_identification,
                "desired_action": desired_action,
                "decision": decision,
                "reason": reason,
            }
        )


class StubAuthService(DeepFaceAuthService):
    def __init__(
        self,
        settings: Settings,
        recognized_person: str | None,
        auth_repository: StubAuthRepository | None = None,
    ):
        super().__init__(settings, auth_repository=auth_repository)
        self._recognized_person = recognized_person

    def recognize_person(
        self,
        frame_bytes: bytes,
        user_record: UserRecord | None = None,
    ) -> tuple[str | None, str]:
        del frame_bytes
        del user_record
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

    def test_authorize_accepts_allowed_action_without_mysql(self):
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
                mysql=None,
            )
            service = StubAuthService(settings, recognized_person="alice")
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("unlock_door", frame)

            self.assertTrue(result["accepted"])
            self.assertEqual(result["decision"], "accepted")
            self.assertEqual(result["person"], "alice")
            self.assertIn("person=alice", log_file.read_text(encoding="utf-8"))
            self.assertIn("decision=accepted", log_file.read_text(encoding="utf-8"))

    def test_authorize_rejects_unknown_person_without_mysql(self):
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
                mysql=None,
            )
            service = StubAuthService(settings, recognized_person=None)
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("set_thermostat", frame)

            self.assertFalse(result["accepted"])
            self.assertEqual(result["decision"], "rejected")
            self.assertIsNone(result["person"])
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn("person=unknown", log_text)
            self.assertIn("action=set_thermostat", log_text)

    def test_authorize_requires_key_when_repository_is_enabled(self):
        settings = self._build_settings()
        user_record = UserRecord(
            user_id=DEFAULT_MYSQL_USER_ID,
            username=DEFAULT_MYSQL_USERNAME,
            key="secret",
        )
        repository = StubAuthRepository(user_record=user_record)
        service = StubAuthService(
            settings,
            recognized_person=DEFAULT_MYSQL_USERNAME,
            auth_repository=repository,
        )
        frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

        with self.assertRaises(ValueError):
            service.authorize("unlock_door", frame)

    def test_authorize_rejects_invalid_key_when_repository_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            log_file = data_dir / "auth.log"
            settings = self._build_settings(data_dir=data_dir, log_file=log_file)
            user_record = UserRecord(
                user_id=DEFAULT_MYSQL_USER_ID,
                username=DEFAULT_MYSQL_USERNAME,
                key="secret",
            )
            repository = StubAuthRepository(user_record=user_record)
            service = StubAuthService(
                settings,
                recognized_person=DEFAULT_MYSQL_USERNAME,
                auth_repository=repository,
            )
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("unlock_door", frame, auth_key="wrong")

            self.assertFalse(result["accepted"])
            self.assertEqual(result["reason"], "invalid_auth_key")
            self.assertEqual(len(repository.events), 1)
            self.assertIsNone(repository.events[0]["user_id"])
            self.assertIn("reason=invalid_auth_key", log_file.read_text(encoding="utf-8"))

    def test_authorize_uses_repository_policy_and_logs_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            log_file = data_dir / "auth.log"
            settings = self._build_settings(data_dir=data_dir, log_file=log_file)
            user_record = UserRecord(
                user_id=DEFAULT_MYSQL_USER_ID,
                username=DEFAULT_MYSQL_USERNAME,
                key="secret",
            )
            repository = StubAuthRepository(
                user_record=user_record,
                allowed_actions={"unlock_door"},
            )
            service = StubAuthService(
                settings,
                recognized_person=DEFAULT_MYSQL_USERNAME,
                auth_repository=repository,
            )
            frame = base64.b64encode(b"jpeg-bytes").decode("ascii")

            result = service.authorize("unlock_door", frame, auth_key="secret")

            self.assertTrue(result["accepted"])
            self.assertEqual(result["person"], DEFAULT_MYSQL_USERNAME)
            self.assertEqual(result["user_id"], DEFAULT_MYSQL_USER_ID)
            self.assertEqual(repository.events[0]["decision"], "accepted")
            self.assertEqual(repository.events[0]["desired_action"], "unlock_door")

    def test_collect_default_user_actions_uses_default_mapping_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            access_file = Path(temp_dir) / "access.yaml"
            access_file.write_text(
                "people:\n"
                "  default:\n"
                "    actions:\n"
                "      - unlock_door\n"
                "  samuel:\n"
                "    actions:\n"
                "      - open_garage\n",
                encoding="utf-8",
            )

            actions = _collect_default_user_actions(access_file)

        self.assertEqual(actions, {"unlock_door"})

    def test_collect_default_user_actions_falls_back_to_union(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            access_file = Path(temp_dir) / "access.yaml"
            access_file.write_text(
                "people:\n"
                "  samuel:\n"
                "    actions:\n"
                "      - unlock_door\n"
                "  alex:\n"
                "    actions:\n"
                "      - open_garage\n",
                encoding="utf-8",
            )

            actions = _collect_default_user_actions(access_file)

        self.assertEqual(actions, {"unlock_door", "open_garage"})

    def test_load_face_entries_reads_supported_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            people_dir = Path(temp_dir) / "people"
            (people_dir / "samuel").mkdir(parents=True, exist_ok=True)
            (people_dir / "samuel" / "front.jpg").write_bytes(b"jpg")
            (people_dir / "samuel" / "profile.png").write_bytes(b"png")
            (people_dir / "samuel" / "notes.txt").write_text("ignore", encoding="utf-8")

            entries = _load_face_entries(people_dir)

        self.assertEqual(
            entries,
            [
                ("samuel/front.jpg", b"jpg"),
                ("samuel/profile.png", b"png"),
            ],
        )

    def test_mysql_settings_from_env_returns_none_without_variables(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(MySQLSettings.from_env())

    def test_mysql_settings_from_env_requires_complete_configuration(self):
        with mock.patch.dict(
            os.environ,
            {
                "DEEPFACE_MYSQL_HOST": "db",
                "DEEPFACE_MYSQL_DATABASE": "deepface",
                "DEEPFACE_MYSQL_USER": "app",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                MySQLSettings.from_env()

    def test_mysql_settings_from_env_builds_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "DEEPFACE_MYSQL_HOST": "db",
                "DEEPFACE_MYSQL_PORT": "3307",
                "DEEPFACE_MYSQL_DATABASE": "deepface",
                "DEEPFACE_MYSQL_USER": "app",
                "DEEPFACE_MYSQL_PASSWORD": "secret",
            },
            clear=True,
        ):
            settings = MySQLSettings.from_env()

        self.assertIsNotNone(settings)
        self.assertEqual(settings.host, "db")
        self.assertEqual(settings.port, 3307)
        self.assertEqual(settings.database, "deepface")
        self.assertEqual(settings.user, "app")
        self.assertEqual(settings.password, "secret")

    @staticmethod
    def _build_settings(
        data_dir: Path | None = None,
        access_file: Path | None = None,
        log_file: Path | None = None,
    ) -> Settings:
        root_dir = data_dir or Path(tempfile.mkdtemp())
        return Settings(
            host="0.0.0.0",
            port=8120,
            data_dir=root_dir,
            access_file=access_file or root_dir / "access.yaml",
            log_file=log_file or root_dir / "auth.log",
            model_name="Facenet512",
            detector_backend="opencv",
            enforce_detection=False,
            mysql=None,
        )


if __name__ == "__main__":
    unittest.main()
