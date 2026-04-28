"""Core logic for camera-based authentication decisions."""

from __future__ import annotations

import base64
import datetime as dt
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

import yaml

DEFAULT_MYSQL_USER_ID = "66bbc3cd-6ad8-49d6-875b-74c16b3ddeb3"
DEFAULT_MYSQL_USERNAME = "default"
DEFAULT_MYSQL_KEY = (
    "a2ecd759be6bd340af29413cc7808f40f5884d2746ddba04d97c4b9fbe0a76ab"
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class UserRecord:
    """A database-backed user record.

    :param user_id: User identifier.
    :param username: User name.
    :param key: Authentication key bound to the user.
    """

    user_id: str
    username: str
    key: str


@dataclass(frozen=True)
class FaceRecord:
    """A stored face enrollment image.

    :param face_id: Face identifier.
    :param face_name: Face label or source path.
    :param face_data: Raw image bytes.
    """

    face_id: str
    face_name: str
    face_data: bytes


class AuthRepository(Protocol):
    """Protocol for optional database-backed auth state."""

    def get_user_by_key(self, auth_key: str) -> UserRecord | None:
        """Find a user by API key."""

    def get_face_records(self, user_id: str) -> list[FaceRecord]:
        """Return enrolled faces for a user."""

    def get_allowed_actions(self, user_id: str) -> set[str]:
        """Return allowed actions for a user."""

    def log_auth_event(
        self,
        timestamp: dt.datetime,
        user_id: str | None,
        person_identification: str,
        desired_action: str,
        decision: str,
        reason: str,
    ) -> None:
        """Persist an authorization event."""


@dataclass(frozen=True)
class MySQLSettings:
    """MySQL connection settings loaded from environment variables.

    :param host: MySQL hostname or service name.
    :param port: MySQL port.
    :param database: Database name.
    :param user: Database username.
    :param password: Database password.
    """

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "MySQLSettings | None":
        """Build optional MySQL settings from process environment.

        :return: MySQL settings when all required fields are present.
        :raises ValueError: If the configuration is incomplete.
        """

        host = os.environ.get("DEEPFACE_MYSQL_HOST", "").strip()
        database = os.environ.get("DEEPFACE_MYSQL_DATABASE", "").strip()
        user = os.environ.get("DEEPFACE_MYSQL_USER", "").strip()
        password = os.environ.get("DEEPFACE_MYSQL_PASSWORD", "")

        populated_fields = [host, database, user, password]
        if not any(populated_fields):
            return None
        if not all(populated_fields):
            raise ValueError(
                "DEEPFACE_MYSQL_HOST, DEEPFACE_MYSQL_DATABASE, DEEPFACE_MYSQL_USER, "
                "and DEEPFACE_MYSQL_PASSWORD must all be set to enable MySQL"
            )

        return cls(
            host=host,
            port=int(os.environ.get("DEEPFACE_MYSQL_PORT", "3306")),
            database=database,
            user=user,
            password=password,
        )


@dataclass(frozen=True)
class Settings:
    """Service configuration loaded from environment variables.

    :param host: Host interface for the API server.
    :param port: API server port.
    :param data_dir: Directory containing enrollment images and policy files.
    :param access_file: YAML policy file path.
    :param log_file: Text audit log output path.
    :param model_name: DeepFace model name.
    :param detector_backend: Face detector backend for DeepFace.
    :param enforce_detection: Whether DeepFace should reject frames without a face.
    :param mysql: Optional MySQL settings.
    """

    host: str
    port: int
    data_dir: Path
    access_file: Path
    log_file: Path
    model_name: str
    detector_backend: str
    enforce_detection: bool
    mysql: MySQLSettings | None

    @classmethod
    def from_env(cls) -> "Settings":
        """Build a settings instance from process environment.

        :return: Normalized settings object.
        """

        data_dir = Path(os.environ.get("DEEPFACE_DATA_DIR", "/data/deepface"))
        access_file = Path(
            os.environ.get("DEEPFACE_ACCESS_FILE", str(data_dir / "access.yaml"))
        )
        log_file = Path(os.environ.get("DEEPFACE_LOG_FILE", str(data_dir / "auth.log")))
        return cls(
            host=os.environ.get("DEEPFACE_HOST", "0.0.0.0"),
            port=int(os.environ.get("DEEPFACE_PORT", "8120")),
            data_dir=data_dir,
            access_file=access_file,
            log_file=log_file,
            model_name=os.environ.get("DEEPFACE_MODEL_NAME", "Facenet512"),
            detector_backend=os.environ.get("DEEPFACE_DETECTOR_BACKEND", "opencv"),
            enforce_detection=_parse_bool(
                os.environ.get("DEEPFACE_ENFORCE_DETECTION", "false")
            ),
            mysql=MySQLSettings.from_env(),
        )


class MySQLAuthRepository:
    """MySQL-backed auth state and audit persistence."""

    def __init__(
        self,
        settings: MySQLSettings,
        data_dir: Path,
        access_file: Path,
    ) -> None:
        self._settings = settings
        self._data_dir = data_dir
        self._access_file = access_file
        self._connector = self._load_connector()
        self._initialize_schema()
        self._seed_default_user_from_filesystem()

    def get_user_by_key(self, auth_key: str) -> UserRecord | None:
        """Find a user row by key."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT userID, username, `key`
                    FROM tblUsers
                    WHERE `key` = %s
                    LIMIT 1
                    """,
                    (auth_key,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return UserRecord(user_id=row[0], username=row[1], key=row[2])

    def get_face_records(self, user_id: str) -> list[FaceRecord]:
        """Return stored face rows for a user."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT faceID, faceName, faceData
                    FROM tblFaces
                    WHERE userID = %s
                    ORDER BY faceName ASC
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall() or []
        return [
            FaceRecord(face_id=row[0], face_name=row[1], face_data=row[2]) for row in rows
        ]

    def get_allowed_actions(self, user_id: str) -> set[str]:
        """Return allowed actions for a user."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT actionName
                    FROM tblAccessRules
                    WHERE userID = %s
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall() or []
        return {
            str(row[0]).strip()
            for row in rows
            if row and isinstance(row[0], str) and row[0].strip()
        }

    def log_auth_event(
        self,
        timestamp: dt.datetime,
        user_id: str | None,
        person_identification: str,
        desired_action: str,
        decision: str,
        reason: str,
    ) -> None:
        """Persist an authorization decision in ``tblAuthLogs``."""

        timestamp_value = timestamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
        log_value = (
            f"person={person_identification};action={desired_action};"
            f"decision={decision};reason={reason}"
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tblAuthLogs (
                        authLogID, `timestamp`, userID, `person identification`
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), timestamp_value, user_id, log_value),
                )
            connection.commit()

    def _initialize_schema(self) -> None:
        """Create required tables when they do not already exist."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tblUsers (
                        userID CHAR(36) NOT NULL,
                        username VARCHAR(255) NOT NULL,
                        `key` VARCHAR(255) NOT NULL,
                        PRIMARY KEY (userID),
                        UNIQUE KEY uq_tblUsers_username (username),
                        UNIQUE KEY uq_tblUsers_key (`key`)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tblFaces (
                        faceID CHAR(36) NOT NULL,
                        faceData LONGBLOB NOT NULL,
                        faceName VARCHAR(255) NOT NULL,
                        userID CHAR(36) NOT NULL,
                        PRIMARY KEY (faceID),
                        UNIQUE KEY uq_tblFaces_user_face (userID, faceName),
                        KEY idx_tblFaces_userID (userID),
                        CONSTRAINT fk_tblFaces_userID
                            FOREIGN KEY (userID) REFERENCES tblUsers(userID)
                            ON DELETE CASCADE
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tblAuthLogs (
                        authLogID CHAR(36) NOT NULL,
                        `timestamp` DATETIME NOT NULL,
                        userID CHAR(36) NULL,
                        `person identification` VARCHAR(255) NOT NULL,
                        PRIMARY KEY (authLogID),
                        KEY idx_tblAuthLogs_userID (userID),
                        CONSTRAINT fk_tblAuthLogs_userID
                            FOREIGN KEY (userID) REFERENCES tblUsers(userID)
                            ON DELETE SET NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tblAccessRules (
                        accessRuleID CHAR(36) NOT NULL,
                        userID CHAR(36) NOT NULL,
                        actionName VARCHAR(255) NOT NULL,
                        PRIMARY KEY (accessRuleID),
                        UNIQUE KEY uq_tblAccessRules_user_action (userID, actionName),
                        KEY idx_tblAccessRules_userID (userID),
                        CONSTRAINT fk_tblAccessRules_userID
                            FOREIGN KEY (userID) REFERENCES tblUsers(userID)
                            ON DELETE CASCADE
                    )
                    """
                )
            connection.commit()

    def _seed_default_user_from_filesystem(self) -> None:
        """Sync default user, access rules, and faces from the filesystem."""

        self._upsert_default_user()
        self._sync_default_access_rules()
        self._sync_default_face_records()

    def _upsert_default_user(self) -> None:
        """Ensure the default MySQL auth user exists."""

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tblUsers (userID, username, `key`)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        username = VALUES(username),
                        `key` = VALUES(`key`)
                    """,
                    (
                        DEFAULT_MYSQL_USER_ID,
                        DEFAULT_MYSQL_USERNAME,
                        DEFAULT_MYSQL_KEY,
                    ),
                )
            connection.commit()

    def _sync_default_access_rules(self) -> None:
        """Replace default-user DB access rules from the YAML configuration."""

        actions = _collect_default_user_actions(self._access_file)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tblAccessRules WHERE userID = %s",
                    (DEFAULT_MYSQL_USER_ID,),
                )
                for action in sorted(actions):
                    cursor.execute(
                        """
                        INSERT INTO tblAccessRules (accessRuleID, userID, actionName)
                        VALUES (%s, %s, %s)
                        """,
                        (str(uuid.uuid4()), DEFAULT_MYSQL_USER_ID, action),
                    )
            connection.commit()

    def _sync_default_face_records(self) -> None:
        """Replace default-user enrolled faces from the filesystem data directory."""

        people_dir = self._data_dir / "people"
        face_entries = _load_face_entries(people_dir)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tblFaces WHERE userID = %s",
                    (DEFAULT_MYSQL_USER_ID,),
                )
                for face_name, face_data in face_entries:
                    cursor.execute(
                        """
                        INSERT INTO tblFaces (faceID, faceData, faceName, userID)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()),
                            face_data,
                            face_name,
                            DEFAULT_MYSQL_USER_ID,
                        ),
                    )
            connection.commit()

    def _connect(self):
        """Open a new MySQL connection."""

        return self._connector.connect(
            host=self._settings.host,
            port=self._settings.port,
            database=self._settings.database,
            user=self._settings.user,
            password=self._settings.password,
        )

    @staticmethod
    def _load_connector():
        """Import the mysql connector lazily so local tests stay lightweight."""

        import mysql.connector

        return mysql.connector


class DeepFaceAuthService:
    """Authenticate requested actions from a single webcam frame.

    :param settings: Runtime settings including paths and DeepFace options.
    :param auth_repository: Optional database-backed auth repository.
    """

    def __init__(
        self,
        settings: Settings,
        auth_repository: AuthRepository | None = None,
    ) -> None:
        self._settings = settings
        if auth_repository is not None:
            self._auth_repository = auth_repository
        elif settings.mysql is not None:
            self._auth_repository = MySQLAuthRepository(
                settings.mysql,
                settings.data_dir,
                settings.access_file,
            )
        else:
            self._auth_repository = None

    def authorize(
        self,
        desired_action: str,
        frame_jpeg_base64: str,
        auth_key: str | None = None,
    ) -> dict[str, Any]:
        """Authorize a requested action using face recognition.

        :param desired_action: Action identifier being requested.
        :param frame_jpeg_base64: Base64-encoded JPEG frame.
        :param auth_key: Optional auth key required for MySQL-backed auth.
        :return: Authorization payload containing decision metadata.
        :raises ValueError: If payload is invalid.
        """

        if not desired_action or not desired_action.strip():
            raise ValueError("desired_action is required")
        frame_bytes = _decode_frame(frame_jpeg_base64)
        normalized_action = desired_action.strip()

        if self._auth_repository is not None:
            return self._authorize_with_repository(
                normalized_action,
                frame_bytes,
                auth_key,
            )

        person, reason = self.recognize_person(frame_bytes)
        policy = load_access_policy(self._settings.access_file)
        accepted = False
        if person:
            accepted = normalized_action in policy.get(person.lower(), set())
            if not accepted:
                reason = "action_not_allowed"
            elif not reason:
                reason = "authorized"

        decision = "accepted" if accepted else "rejected"
        self._append_auth_log(
            person,
            normalized_action,
            decision,
            reason or "unrecognized",
        )
        return {
            "person": person,
            "desired_action": normalized_action,
            "accepted": accepted,
            "decision": decision,
            "reason": reason or "unrecognized",
        }

    def _authorize_with_repository(
        self,
        desired_action: str,
        frame_bytes: bytes,
        auth_key: str | None,
    ) -> dict[str, Any]:
        """Authorize a request using the configured repository."""

        normalized_key = (auth_key or "").strip()
        if not normalized_key:
            raise ValueError("auth_key is required")

        user_record = self._auth_repository.get_user_by_key(normalized_key)
        if user_record is None:
            decision = "rejected"
            reason = "invalid_auth_key"
            self._append_auth_log(
                None,
                desired_action,
                decision,
                reason,
            )
            return {
                "person": None,
                "user_id": None,
                "desired_action": desired_action,
                "accepted": False,
                "decision": decision,
                "reason": reason,
            }

        person, reason = self.recognize_person(frame_bytes, user_record=user_record)
        allowed_actions = self._auth_repository.get_allowed_actions(user_record.user_id)
        accepted = False
        if person:
            accepted = desired_action in allowed_actions
            if not accepted:
                reason = "action_not_allowed"
            elif not reason:
                reason = "authorized"

        decision = "accepted" if accepted else "rejected"
        self._append_auth_log(
            person,
            desired_action,
            decision,
            reason or "unrecognized",
            user_id=user_record.user_id,
        )
        return {
            "person": person,
            "user_id": user_record.user_id,
            "desired_action": desired_action,
            "accepted": accepted,
            "decision": decision,
            "reason": reason or "unrecognized",
        }

    def recognize_person(
        self,
        frame_bytes: bytes,
        user_record: UserRecord | None = None,
    ) -> tuple[str | None, str]:
        """Identify the closest enrolled person in the provided frame.

        :param frame_bytes: Raw JPEG bytes captured from webcam.
        :param user_record: Optional DB-backed user record for keyed face lookup.
        :return: Tuple of person name and match reason.
        """

        people_dir: Path | None = None
        temp_db_dir: tempfile.TemporaryDirectory[str] | None = None
        image_path: Path | None = None
        try:
            if user_record is not None and self._auth_repository is not None:
                face_records = self._auth_repository.get_face_records(user_record.user_id)
                if not face_records:
                    return None, "no_enrolled_faces"
                temp_db_dir = tempfile.TemporaryDirectory()
                people_dir = _materialize_face_records(
                    Path(temp_db_dir.name),
                    user_record.username,
                    face_records,
                )
            else:
                people_dir = self._settings.data_dir / "people"
                if not people_dir.exists():
                    return None, "people_directory_missing"

            with NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                temp_file.write(frame_bytes)
                image_path = Path(temp_file.name)

            from deepface import DeepFace

            result = DeepFace.find(
                img_path=str(image_path),
                db_path=str(people_dir),
                model_name=self._settings.model_name,
                detector_backend=self._settings.detector_backend,
                enforce_detection=self._settings.enforce_detection,
                silent=True,
            )
            person = _extract_person_from_find_result(result, people_dir)
            if not person:
                return None, "no_face_match"
            return person, "authorized"
        except Exception:
            return None, "recognition_error"
        finally:
            if image_path is not None:
                image_path.unlink(missing_ok=True)
            if temp_db_dir is not None:
                temp_db_dir.cleanup()

    def _append_auth_log(
        self,
        person: str | None,
        desired_action: str,
        decision: str,
        reason: str,
        user_id: str | None = None,
    ) -> None:
        """Append a structured auth decision line to the audit log."""

        timestamp = dt.datetime.now(dt.timezone.utc)
        self._settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        actor = person if person else "unknown"
        with self._settings.log_file.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{timestamp.isoformat()}\tperson={actor}\taction={desired_action}"
                f"\tdecision={decision}\treason={reason}\n"
            )
        if self._auth_repository is not None:
            self._auth_repository.log_auth_event(
                timestamp=timestamp,
                user_id=user_id,
                person_identification=actor,
                desired_action=desired_action,
                decision=decision,
                reason=reason,
            )


def load_access_policy(path: Path) -> dict[str, set[str]]:
    """Load action permissions per person from a YAML policy file.

    :param path: Policy file path.
    :return: Mapping of lowercase person names to allowed actions.
    """

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    people_payload: dict[str, Any]
    if isinstance(payload, dict) and isinstance(payload.get("people"), dict):
        people_payload = payload["people"]
    elif isinstance(payload, dict):
        people_payload = payload
    else:
        return {}

    normalized: dict[str, set[str]] = {}
    for person, raw_rules in people_payload.items():
        name = str(person).strip().lower()
        if not name:
            continue
        actions: list[str] = []
        if isinstance(raw_rules, dict):
            raw_actions = raw_rules.get("actions", [])
            if isinstance(raw_actions, list):
                actions = [str(item).strip() for item in raw_actions]
        elif isinstance(raw_rules, list):
            actions = [str(item).strip() for item in raw_rules]
        normalized[name] = {action for action in actions if action}
    return normalized


def _decode_frame(frame_jpeg_base64: str) -> bytes:
    """Decode a base64-encoded frame string.

    :param frame_jpeg_base64: Base64 frame payload.
    :return: Decoded frame bytes.
    :raises ValueError: If payload cannot be decoded.
    """

    try:
        decoded = base64.b64decode(frame_jpeg_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid frame_jpeg_base64") from exc
    if not decoded:
        raise ValueError("empty frame payload")
    return decoded


def _extract_person_from_find_result(result: Any, people_dir: Path) -> str | None:
    """Extract the person directory name from a DeepFace result."""

    frames = result if isinstance(result, list) else [result]
    for frame in frames:
        identity = _extract_identity(frame)
        if not identity:
            continue
        person = _extract_person_name(identity, people_dir)
        if person:
            return person
    return None


def _extract_identity(frame: Any) -> str | None:
    """Extract a candidate identity path from dataframe-like payload."""

    if isinstance(frame, dict):
        identity_value = frame.get("identity")
        if isinstance(identity_value, str) and identity_value.strip():
            return identity_value
        return None

    empty_attr = getattr(frame, "empty", None)
    if empty_attr is True:
        return None

    iloc = getattr(frame, "iloc", None)
    if iloc is None:
        return None

    try:
        row = iloc[0]
    except Exception:
        return None

    try:
        identity_value = row.get("identity")
    except Exception:
        return None

    if isinstance(identity_value, str) and identity_value.strip():
        return identity_value
    return None


def _extract_person_name(identity: str, people_dir: Path) -> str | None:
    """Resolve person name from an identity image path."""

    identity_path = Path(identity)
    try:
        rel_path = identity_path.relative_to(people_dir)
    except ValueError:
        people_parts = people_dir.parts
        identity_parts = identity_path.parts
        for idx in range(len(identity_parts) - len(people_parts) + 1):
            if identity_parts[idx : idx + len(people_parts)] == people_parts:
                if idx + len(people_parts) < len(identity_parts):
                    person = identity_parts[idx + len(people_parts)]
                    return person.strip().lower() if person.strip() else None
        person_name = identity_path.parent.name
        return person_name.strip().lower() if person_name.strip() else None

    if not rel_path.parts:
        return None
    person_name = rel_path.parts[0]
    return person_name.strip().lower() if person_name.strip() else None


def _parse_bool(value: str) -> bool:
    """Parse boolean-like strings."""

    lowered = value.strip().lower()
    return lowered in {"1", "true", "yes", "on"}


def _collect_default_user_actions(path: Path) -> set[str]:
    """Collect filesystem access rules for import into the default DB user."""

    policy = load_access_policy(path)
    actions: set[str] = set()
    default_actions = policy.get(DEFAULT_MYSQL_USERNAME, set())
    if default_actions:
        actions.update(default_actions)
    else:
        for person_actions in policy.values():
            actions.update(person_actions)
    return {action for action in actions if action}


def _load_face_entries(people_dir: Path) -> list[tuple[str, bytes]]:
    """Load enrollment image bytes from the filesystem."""

    if not people_dir.exists():
        return []

    face_entries: list[tuple[str, bytes]] = []
    for path in sorted(people_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        relative_name = path.relative_to(people_dir).as_posix()
        face_entries.append((relative_name, path.read_bytes()))
    return face_entries


def _materialize_face_records(
    root_dir: Path,
    username: str,
    face_records: list[FaceRecord],
) -> Path:
    """Write DB face blobs to a temporary DeepFace enrollment directory."""

    people_dir = root_dir / username.strip().lower()
    people_dir.mkdir(parents=True, exist_ok=True)
    for index, face_record in enumerate(face_records, start=1):
        suffix = Path(face_record.face_name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            suffix = ".jpg"
        file_name = _sanitize_face_name(face_record.face_name, index, suffix)
        target_path = people_dir / file_name
        target_path.write_bytes(face_record.face_data)
    return root_dir


def _sanitize_face_name(face_name: str, index: int, suffix: str) -> str:
    """Create a stable file name for temporary face records."""

    stem = Path(face_name).stem.strip().lower()
    normalized = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in stem
    ).strip("_")
    if not normalized:
        normalized = f"face_{index}"
    return f"{normalized}{suffix}"
