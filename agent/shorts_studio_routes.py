"""FastAPI routes for Shorts Studio scene revisions and project history."""

from copy import deepcopy
import shutil

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


def _route_exists(app, path, method):
    method = str(method).upper()
    return any(
        getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
        for route in app.routes
    )


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


def _history_groups(jobs):
    groups = {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        item = dict(job)
        item.setdefault("id", str(job_id))
        root_id = _history_root_id(item, jobs)
        groups.setdefault(root_id, []).append(item)
    return groups


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

    groups = _history_groups(jobs)
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


def _safe_job_directory(job_id):
    safe_job_id = shorts_jobs._job_id(job_id)
    root = shorts_jobs.SHORTS_DIRECTORY.expanduser().resolve()
    candidate = root / safe_job_id

    # Resolve the parent, not the candidate itself, so a malicious symlink at
    # candidate cannot escape the managed Shorts directory during deletion.
    if candidate.parent.resolve() != root:
        raise ValueError("invalid Shorts project path")
    if candidate.is_symlink():
        raise ValueError("Shorts project directory must not be a symlink")
    return candidate


def _worker_is_active(job_id):
    with shorts_jobs._workers_lock:
        worker = shorts_jobs._workers.get(job_id)
        return bool(worker is not None and worker.is_alive())


def _project_job_ids(job_id, jobs):
    safe_job_id = shorts_jobs._job_id(job_id)
    selected = jobs.get(safe_job_id)
    if not isinstance(selected, dict):
        raise KeyError("short job not found")

    selected = dict(selected)
    selected.setdefault("id", safe_job_id)
    root_id = _history_root_id(selected, jobs)
    project_ids = []
    for candidate_id, candidate in jobs.items():
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        item.setdefault("id", str(candidate_id))
        if _history_root_id(item, jobs) == root_id:
            project_ids.append(str(candidate_id))
    return root_id, project_ids


def _delete_project_from_store(job_id):
    """Delete one complete immutable revision chain and its Shorts-owned files."""
    with shorts_jobs._jobs_lock:
        jobs = shorts_jobs._load_jobs()
        root_id, project_ids = _project_job_ids(job_id, jobs)

        active_ids = [
            candidate_id
            for candidate_id in project_ids
            if str(jobs[candidate_id].get("status") or "") in shorts_jobs.ACTIVE_STATUSES
            or _worker_is_active(candidate_id)
        ]
        if active_ids:
            raise ValueError("active Shorts projects must be cancelled before deletion")

        directories = [_safe_job_directory(candidate_id) for candidate_id in project_ids]
        updated = dict(jobs)
        for candidate_id in project_ids:
            updated.pop(candidate_id, None)
        shorts_jobs._save_jobs(updated)

    cleanup_errors = []
    for directory in directories:
        try:
            if directory.exists():
                shutil.rmtree(directory)
        except OSError as exc:
            cleanup_errors.append(f"{directory.name}: {exc}")

    return {
        "deleted": True,
        "root_job_id": root_id,
        "deleted_jobs": len(project_ids),
        "deleted_job_ids": sorted(project_ids),
        "cleanup_errors": cleanup_errors,
    }


def delete_short_project(job_id):
    return _delete_project_from_store(job_id)


def delete_failed_short_projects():
    """Delete projects whose latest revision is failed; never touch active chains."""
    with shorts_jobs._jobs_lock:
        jobs = deepcopy(shorts_jobs._load_jobs())

    groups = _history_groups(jobs)
    failed_roots = []
    for root_id, revisions in groups.items():
        revisions.sort(key=_job_timestamp)
        if str(revisions[-1].get("status") or "") == "failed":
            failed_roots.append(root_id)

    deleted_projects = 0
    deleted_jobs = 0
    deleted_job_ids = []
    skipped_active = []
    cleanup_errors = []

    for root_id in failed_roots:
        try:
            result = _delete_project_from_store(root_id)
        except ValueError:
            skipped_active.append(root_id)
            continue
        except KeyError:
            # Another deletion in this same request may already have removed a
            # malformed/cross-linked chain. Treat it as gone instead of failing.
            continue
        deleted_projects += 1
        deleted_jobs += int(result.get("deleted_jobs") or 0)
        deleted_job_ids.extend(result.get("deleted_job_ids") or [])
        cleanup_errors.extend(result.get("cleanup_errors") or [])

    return {
        "deleted_projects": deleted_projects,
        "deleted_jobs": deleted_jobs,
        "deleted_job_ids": sorted(set(deleted_job_ids)),
        "skipped_active": skipped_active,
        "cleanup_errors": cleanup_errors,
    }


def install_routes(app):
    """Register Shorts Studio routes exactly once on an existing FastAPI app."""
    history_path = "/api/shorts-jobs"
    if not _route_exists(app, history_path, "GET"):
        @app.get(history_path)
        def shorts_history(limit: int = 50):
            return list_short_history(limit=limit)

    failed_cleanup_path = "/api/shorts-jobs/failed"
    if not _route_exists(app, failed_cleanup_path, "DELETE"):
        @app.delete(failed_cleanup_path)
        def delete_failed_shorts():
            return delete_failed_short_projects()

    delete_path = "/api/shorts-jobs/{job_id}"
    if not _route_exists(app, delete_path, "DELETE"):
        @app.delete(delete_path)
        def delete_short(job_id: str):
            try:
                return delete_short_project(job_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Shorts job not found") from exc
            except ValueError as exc:
                detail = str(exc)
                status = 409 if "active Shorts projects" in detail else 400
                raise HTTPException(status_code=status, detail=detail) from exc

    revision_path = "/api/shorts/jobs/{job_id}/scenes/{scene_id}/revise"
    if not _route_exists(app, revision_path, "POST"):
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
