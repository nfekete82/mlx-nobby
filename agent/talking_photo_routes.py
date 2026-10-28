"""FastAPI routes for the local Talking Photo feature."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from agent import (
    talking_photo,
    talking_photo_lifecycle,
    talking_photo_quality,
)


class PersonFocus(BaseModel):
    """Exact normalized position of the person clicked in the photo."""
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class TalkingPhotoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    image_data_url: str = Field(min_length=32)
    text: str = Field(min_length=1, max_length=5000)
    voice: str | None = Field(default=None, max_length=80)
    language: str = Field(default="de", min_length=2, max_length=16, pattern=r"^[A-Za-z-]+$")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    motion: Literal["none", "natural"] = "natural"
    engine: Literal["ltx", "ltx-distilled", "ltx-max"] = "ltx-distilled"
    lead_in_ms: Literal[0, 500] = 0  # Opt-in LTX-only A/B experiment
    person_focus: PersonFocus | None = None  # Prompt-guided LTX speaker selection


def provider_status() -> dict:
    """Only report native LTX, without contacting the retired MuseTalk server."""
    ltx = talking_photo_quality.direct_provider_health()
    return {
        "ready": bool(ltx.get("ready")),
        "provider": ltx.get("provider"),
        "device": ltx.get("device"),
        "setup_command": ltx.get("setup_command"),
        "detail": ltx.get("detail"),
        "default_engine": "ltx-distilled",
        "max_longform_audio_seconds": 60,
        "ltx_available": bool(ltx.get("ready")),
        "ltx_distilled_available": bool(ltx.get("ready")),
        "ltx_max_available": bool(ltx.get("ready")),
        "providers": {
            "ltx": ltx,
            "ltx-distilled": ltx,
            "ltx-max": ltx,
        },
    }


def install_routes(app):
    talking_photo.recover_jobs()
    methods_by_path = {
        (getattr(route, "path", None), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }

    if ("/api/talking-photo/status", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/status")
        def talking_photo_status():
            return provider_status()

    if ("/api/talking-photo/jobs", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs", status_code=202)
        def talking_photo_create(request: TalkingPhotoRequest):
            payload = request.model_dump()
            engine = payload.pop("engine", "ltx-distilled")
            if engine == "ltx":
                return talking_photo_quality.create_job(payload, ltx_only=True)
            if engine == "ltx-max":
                return talking_photo_quality.create_job(payload, ltx_only=True, stage1_steps=30)
            return talking_photo_quality.create_job(payload, ltx_only=True, distilled=True)

    if ("/api/talking-photo/jobs/{job_id}", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/jobs/{job_id}")
        def talking_photo_job(job_id: str):
            return talking_photo_lifecycle.get_job(job_id)

    if ("/api/talking-photo/jobs/{job_id}/cancel", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/cancel")
        def talking_photo_cancel(job_id: str):
            return talking_photo.cancel_job(job_id)

    if ("/api/talking-photo/jobs/{job_id}/keep", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/keep")
        def talking_photo_keep(job_id: str):
            try:
                return talking_photo_lifecycle.keep_job(job_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    if ("/api/talking-photo/jobs/{job_id}/discard", "POST") not in methods_by_path:
        @app.post("/api/talking-photo/jobs/{job_id}/discard")
        def talking_photo_discard(job_id: str):
            return talking_photo_lifecycle.discard_job(job_id)

    if ("/api/talking-photo/videos/{video_id}", "GET") not in methods_by_path:
        @app.get("/api/talking-photo/videos/{video_id}")
        def talking_photo_video(video_id: str, download: bool = False):
            return FileResponse(
                talking_photo.video_path(video_id),
                media_type="video/mp4",
                filename=f"talking-photo-{video_id}.mp4",
                headers={"Cache-Control": "no-store"},
            )
