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


class TalkingPhotoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    image_data_url: str = Field(min_length=32)
    text: str = Field(min_length=1, max_length=5000)
    voice: str | None = Field(default=None, max_length=80)
    language: str = Field(default="de", min_length=2, max_length=16, pattern=r"^[A-Za-z-]+$")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    motion: Literal["none", "natural"] = "none"
    engine: Literal["auto", "fast", "quality"] = "auto"


def provider_status() -> dict:
    fast = talking_photo.provider_health()
    quality = talking_photo_quality.provider_health()
    preferred = quality if quality.get("ready") else fast
    return {
        "ready": bool(preferred.get("ready")),
        "provider": preferred.get("provider"),
        "device": preferred.get("device"),
        "setup_command": preferred.get("setup_command"),
        "detail": preferred.get("detail"),
        "default_engine": "quality" if quality.get("ready") else "fast",
        "providers": {
            "fast": fast,
            "quality": quality,
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
            engine = payload.pop("engine", "auto")
            if engine == "quality":
                return talking_photo_quality.create_job(payload)
            if engine == "fast":
                return talking_photo.create_job(payload)
            if talking_photo_quality.provider_health().get("ready"):
                return talking_photo_quality.create_job(payload)
            return talking_photo.create_job(payload)

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
