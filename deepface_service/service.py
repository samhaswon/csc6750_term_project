"""Core logic for camera-based authentication decisions."""

from __future__ import annotations

import base64
import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


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
    """

    host: str
    port: int
    data_dir: Path
    access_file: Path
    log_file: Path
    model_name: str
    detector_backend: str
    enforce_detection: bool

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
        )


class DeepFaceAuthService:
    """Authenticate requested actions from a single webcam frame.

    :param settings: Runtime settings including paths and DeepFace options.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize(self, desired_action: str, frame_jpeg_base64: str) -> dict[str, Any]:
        """Authorize a requested action using face recognition.

        :param desired_action: Action identifier being requested.
        :param frame_jpeg_base64: Base64-encoded JPEG frame.
        :return: Authorization payload containing decision metadata.
        :raises ValueError: If payload is invalid.
        """

        if not desired_action or not desired_action.strip():
            raise ValueError("desired_action is required")
        frame_bytes = _decode_frame(frame_jpeg_base64)
        person, reason = self.recognize_person(frame_bytes)
        policy = load_access_policy(self._settings.access_file)
        normalized_action = desired_action.strip()

        accepted = False
        if person:
            accepted = normalized_action in policy.get(person.lower(), set())
            if not accepted:
                reason = "action_not_allowed"
            elif not reason:
                reason = "authorized"

        decision = "accepted" if accepted else "rejected"
        self._append_auth_log(person, normalized_action, decision)

        return {
            "person": person,
            "desired_action": normalized_action,
            "accepted": accepted,
            "decision": decision,
            "reason": reason or "unrecognized",
        }

    def recognize_person(self, frame_bytes: bytes) -> tuple[str | None, str]:
        """Identify the closest enrolled person in the provided frame.

        :param frame_bytes: Raw JPEG bytes captured from webcam.
        :return: Tuple of person name and match reason.
        """

        people_dir = self._settings.data_dir / "people"
        if not people_dir.exists():
            return None, "people_directory_missing"

        image_path: Path | None = None
        try:
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

    def _append_auth_log(
            self, person: str | None, desired_action: str, decision: str
    ) -> None:
        """Append a structured auth decision line to the audit log.

        :param person: Recognized person name, if any.
        :param desired_action: Action requested by caller.
        :param decision: Decision string, accepted or rejected.
        """

        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        self._settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        actor = person if person else "unknown"
        with self._settings.log_file.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{timestamp}\tperson={actor}\taction={desired_action}"
                f"\tdecision={decision}\n"
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
    """Extract the person directory name from a DeepFace result.

    :param result: Return value from ``DeepFace.find``.
    :param people_dir: Base directory for enrolled faces.
    :return: Person name if a match is present, otherwise ``None``.
    """

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
    """Extract a candidate identity path from dataframe-like payload.

    :param frame: DataFrame-like object returned by DeepFace.
    :return: Identity path if available.
    """

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
    """Resolve person name from an identity image path.

    :param identity: Matched image path emitted by DeepFace.
    :param people_dir: Enrollment root directory.
    :return: Person name if parsing succeeds.
    """

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
    """Parse boolean-like strings.

    :param value: Input value.
    :return: Parsed boolean.
    """

    lowered = value.strip().lower()
    return lowered in {"1", "true", "yes", "on"}
