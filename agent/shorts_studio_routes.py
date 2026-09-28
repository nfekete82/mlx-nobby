"""FastAPI routes for Shorts Studio scene revisions and project history."""

from copy import deepcopy

from fastapi import HTTPException
from pydantic import BaseModel, Field

from agent import shorts_jobs
from agent.shorts_studio import create_scene_revision


class SceneRevisionRequest(BaseModel):
    narration: str | None = Field(default=None, min_length=1, max_length=4000)
    video_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    force_regenerate_video: bool = False
    force_regenerate_keyframe: bool = False
    voice: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)
    consistency_mode: bool | None = None
    character_consistency: bool | None = None
    style_consistency: bool | None = None
    style_strength: float | None = Field(default=None, ge=0.0, le=1.0)


def _job_timestamp(job):
    for key in ("finished_at", "started_at", "created_at"):
        try:
            value = float(job.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _history_root_id(job, jobs):
    current = job
    seen = set()

    while isinstance(current, dict):
        current_id = str(current.get("id") or "")
        if not current_id or current_id in seen:
            break
        seen.add(current_id)

        parent_id = str(current.get("parent_job_id") or "")
        parent = jobs.get(parent_id)
        if not parent_id or not isinstance(parent, dict):
            return current_id
        current = parent

    return str(job.get("id") or "")


def _history_summary(job, *, root_id, revision_count):
    project = job.get("project") if isinstance(job.get("project"), dict) else {}
    scenes = project.get("scenes") if isinstance(project.get("scenes"), list) else []
    status = str(job.get("status") or "unknown")
    current_scene = job.get("current_scene")
    try:
        current_scene = max(0, min(int(current_scene or 0), len(scenes)))
    except (TypeError, ValueError):
        current_scene = 0

    if status == "completed":
        progress = 1.0
    elif scenes:
        progress = current_scene / len(scenes)
    else:
        progress = 0.0

    return {
        "id": str(job.get("id") or ""),
        "root_job_id": root_id,
        "parent_job_id": job.get("parent_job_id"),
        "revision_count": max(0, int(revision_count)),
        "title": str(project.get("title") or "Short"),
        "status": status,
        "phase": str(job.get("phase") or status),
        "duration": project.get("duration") or 0,
        "voice": project.get("voice"),
        "voice_speed": project.get("voice_speed", 1.0),
        "scene_count": len(scenes),
        "current_scene": current_scene,
        "progress": round(max(0.0, min(float(progress), 1.0)), 4),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": _job_timestamp(job),
        "chat_id": job.get("chat_id"),
        "error": job.get("error"),
        "has_video": bool(status == "completed" and job.get("final_path")),
    }


def list_short_history(limit=50):
    """Return latest revision per Shorts project, newest first."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    with shorts_jobs._jobs_lock:
        jobs = deepcopy(shorts_jobs._load_jobs())

    groups = {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        item = dict(job)
        item.setdefault("id", str(job_id))
        root_id = _history_root_id(item, jobs)
        groups.setdefault(root_id, []).append(item)

    summaries = []
    for root_id, revisions in groups.items():
        revisions.sort(key=_job_timestamp)
        latest = revisions[-1]
        summaries.append(
            _history_summary(
                latest,
                root_id=root_id,
                revision_count=len(revisions) - 1,
            )
        )

    summaries.sort(
        key=lambda item: float(item.get("updated_at") or 0.0),
        reverse=True,
    )
    total = len(summaries)
    return {
        "projects": summaries[:limit],
        "total": total,
        "limit": limit,
    }


def install_routes(app):
    """Register Shorts Studio routes exactly once on an existing FastAPI app."""
    paths = {getattr(route, "path", None) for route in app.routes}

    history_path = "/api/shorts-jobs"
    if history_path not in paths:
        @app.get(history_path)
        def shorts_history(limit: int = 50):
            return list_short_history(limit=limit)

    revision_path = "/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise"
    if revision_path not in paths:
        @app.post(revision_path, status_code=202)
        def revise_short_scene(
            job_id: str,
            scene_id: str,
            request: SceneRevisionRequest,
        ):
            revision_options = {
                "narration": request.narration,
                "video_prompt": request.video_prompt,
                "force_regenerate_video": request.force_regenerate_video,
                "voice": request.voice,
                "voice_speed": request.voice_speed,
            }
            # Preserve the established call shape for legacy clients/tests. New
            # options participate only when a caller explicitly requests them.
            if request.force_regenerate_keyframe:
                revision_options["force_regenerate_keyframe"] = True
            if request.consistency_mode is not None:
                revision_options["consistency_mode"] = request.consistency_mode
            if request.character_consistency is not None:
                revision_options["character_consistency"] = request.character_consistency
            if request.style_consistency is not None:
                revision_options["style_consistency"] = request.style_consistency
            if request.style_strength is not None:
                revision_options["style_strength"] = request.style_strength

            try:
                revised = create_scene_revision(
                    job_id,
                    scene_id,
                    **revision_options,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Shorts job not found") from exc
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            shorts_jobs.start_short_job(revised["id"])
            return {"job": revised}

    return app
