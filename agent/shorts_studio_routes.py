"""FastAPI routes for Shorts Studio scene revisions."""

from fastapi import HTTPException
from pydantic import BaseModel, Field

from agent import shorts_jobs
from agent.shorts_studio import create_scene_revision


class SceneRevisionRequest(BaseModel):
    narration: str | None = Field(default=None, min_length=1, max_length=4000)
    video_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    force_regenerate_video: bool = False
    voice: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)


def install_routes(app):
    """Register Shorts Studio routes exactly once on an existing FastAPI app."""
    route_path = "/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise"
    if any(getattr(route, "path", None) == route_path for route in app.routes):
        return app

    @app.post(route_path, status_code=202)
    def revise_short_scene(
        job_id: str,
        scene_id: str,
        request: SceneRevisionRequest,
    ):
        try:
            revised = create_scene_revision(
                job_id,
                scene_id,
                narration=request.narration,
                video_prompt=request.video_prompt,
                force_regenerate_video=request.force_regenerate_video,
                voice=request.voice,
                voice_speed=request.voice_speed,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Shorts job not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        shorts_jobs.start_short_job(revised["id"])
        return {"job": revised}

    return app
