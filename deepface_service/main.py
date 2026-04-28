"""FastAPI entrypoint for DeepFace-based authorization."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from deepface_service.service import DeepFaceAuthService, Settings


class AuthRequest(BaseModel):
    """Authorization request payload.

    :param desired_action: Action identifier requested by caller.
    :param frame_jpeg_base64: Base64-encoded JPEG frame captured by caller.
    :param auth_key: Optional key used for MySQL-backed face and policy lookup.
    """

    desired_action: str = Field(..., min_length=1)
    frame_jpeg_base64: str = Field(..., min_length=1)
    auth_key: str | None = Field(default=None, min_length=1)


SETTINGS = Settings.from_env()
AUTH = DeepFaceAuthService(SETTINGS)
app = FastAPI(title="DeepFace Auth Service", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, object]:
    """Expose service readiness details.

    :return: Health payload for orchestration checks.
    """

    return {
        "status": "ok",
        "data_dir": str(SETTINGS.data_dir),
        "access_file": str(SETTINGS.access_file),
        "log_file": str(SETTINGS.log_file),
        "mysql_enabled": SETTINGS.mysql is not None,
        "model_name": SETTINGS.model_name,
        "detector_backend": SETTINGS.detector_backend,
    }


@app.post("/auth/authorize")
async def authorize(payload: AuthRequest) -> dict[str, object]:
    """Authorize an action by matching webcam frame against enrolled faces.

    :param payload: Action and frame payload.
    :return: Authorization decision details.
    """

    try:
        return AUTH.authorize(
            payload.desired_action,
            payload.frame_jpeg_base64,
            auth_key=payload.auth_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"authorization failed: {exc}") from exc
