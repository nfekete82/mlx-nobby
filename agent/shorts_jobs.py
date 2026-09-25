"""Persistent, resumable orchestration of ShortProject video scenes."""

from copy import deepcopy
from pathlib import Path
import re
import threading
import time
import uuid

from agent import batch_state, video_api
from agent.shorts_planner import ShortProject


SHORTS_DIRECTORY = Path.home() / ".config/mlx-web/shorts"
SHORTS_JOBS_FILE = SHORTS_DIRECTORY / "jobs.json"
SHORT_JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"video_completed", "failed", "cancelled"}
VIDEO_ACTIVE_STATUSES = {
    "queued", "loading", "encoding", "generating",
    "upscaling", "decoding", "muxing",
}

_jobs_lock = threading.RLock()
_workers_lock = threading.Lock()
_workers = {}


def _load_jobs():
    return batch_state.load_jobs(SHORTS_JOBS_FILE)


def _save_jobs(jobs):
    batch_state.save_jobs(SHORTS_DIRECTORY, SHORTS_JOBS_FILE, jobs)


def _job_id(value):
    value = str(value or "")
    if not SHORT_JOB_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid short job id")
    return value


def get_short_job(job_id):
    job_id = _job_id(job_id)
    with _jobs_lock:
        job = _load_jobs().get(job_id)
    if job is None:
        raise KeyError("short job not found")
    return deepcopy(job)


def create_short_job(project, *, chat_id, run_id=None, chat_revision=0):
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    if not isinstance(chat_id, str) or not chat_id.strip():
        raise ValueError("chat_id is required")
    if isinstance(chat_revision, bool) or not isinstance(chat_revision, int) or chat_revision < 0:
        raise ValueError("chat_revision must be a non-negative integer")

    job_id = uuid.uuid4().hex[:24]
    job = {
        "id": job_id,
        "kind": "shorts",
        "chat_id": chat_id,
        "run_id": str(run_id or uuid.uuid4().hex),
        "chat_revision": chat_revision,
        "status": "queued",
        "phase": "queued",
        "project": project.model_dump(mode="json"),
        "current_scene": 0,
        "scene_results": [],
        "active_video_job_id": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "cancel_requested": False,
    }
    with _jobs_lock:
        jobs = _load_jobs()
        jobs[job_id] = job
        _save_jobs(jobs)
    return deepcopy(job)


def _update_job(job_id, **changes):
    with _jobs_lock:
        jobs = _load_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise KeyError("short job not found")
        if job.get("status") in TERMINAL_STATUSES:
            return deepcopy(job)
        job.update(changes)
        jobs[job_id] = job
        _save_jobs(jobs)
        return deepcopy(job)


def _video_request(request_fn, method, path, payload=None, timeout=15):
    return request_fn(method, path, payload, timeout=timeout)


def _retryable_service_error(exc, *status_codes):
    return getattr(exc, "status_code", None) in status_codes


def _scene_request(job, scene):
    return {
        "operation": "t2v",
        "payload": {
            "prompt": scene["video_prompt"],
            "duration": scene["duration"],
            "aspect_ratio": job["project"]["aspect_ratio"],
            # Fast supports every duration accepted by ShortProject.
            "quality": "fast",
        },
        "chat_id": job["chat_id"],
        "run_id": job["run_id"],
        "chat_revision": job["chat_revision"],
    }


def _completed_scene_ids(job):
    return {
        result.get("scene_id")
        for result in job.get("scene_results", [])
        if result.get("status") == "completed"
    }


def _cancel_active_video(job, request_fn):
    child_id = job.get("active_video_job_id")
    if not child_id:
        return
    try:
        _video_request(
            request_fn,
            "POST",
            "/jobs/" + video_api.job_id(child_id) + "/cancel",
            {},
            timeout=30,
        )
    except Exception:
        # Best effort: the durable parent state still prevents consumption.
        pass


def _finish_cancelled(job_id, request_fn):
    job = get_short_job(job_id)
    _cancel_active_video(job, request_fn)
    with _jobs_lock:
        jobs = _load_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise KeyError("short job not found")
        if job.get("status") == "video_completed":
            return deepcopy(job)
        job.update(
            cancel_requested=True,
            status="cancelled",
            phase="cancelled",
            finished_at=time.time(),
            error=None,
        )
        jobs[job_id] = job
        _save_jobs(jobs)
        return deepcopy(job)


def run_short_job(job_id, *, request_fn=None, poll_interval=1.0):
    """Run or resume one job synchronously; workers call this in a thread."""
    job_id = _job_id(job_id)
    request_fn = request_fn or video_api.request
    job = get_short_job(job_id)
    if job.get("status") in TERMINAL_STATUSES:
        return job
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    _update_job(
        job_id,
        status="running",
        phase="video",
        started_at=job.get("started_at") or time.time(),
        error=None,
    )

    try:
        while True:
            job = get_short_job(job_id)
            if job.get("status") in TERMINAL_STATUSES:
                return job
            if job.get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)

            project = ShortProject.model_validate(job["project"])
            completed_ids = _completed_scene_ids(job)
            scene_index = 0
            while (
                scene_index < len(project.scenes)
                and project.scenes[scene_index].id in completed_ids
            ):
                scene_index += 1

            if scene_index >= len(project.scenes):
                return _update_job(
                    job_id,
                    status="video_completed",
                    phase="video_completed",
                    current_scene=len(project.scenes),
                    active_video_job_id=None,
                    finished_at=time.time(),
                    error=None,
                )

            if scene_index != job.get("current_scene"):
                job = _update_job(job_id, current_scene=scene_index)

            scene = project.scenes[scene_index].model_dump(mode="json")
            child_id = job.get("active_video_job_id")
            if not child_id:
                try:
                    child = _video_request(
                        request_fn,
                        "POST",
                        "/jobs",
                        _scene_request(job, scene),
                        timeout=15,
                    )
                except Exception as exc:
                    if _retryable_service_error(exc, 409, 503):
                        time.sleep(max(poll_interval, 0.1))
                        continue
                    raise
                child_id = video_api.job_id(child.get("id"))
                job = _update_job(
                    job_id,
                    active_video_job_id=child_id,
                    phase="video",
                )

            try:
                child = _video_request(
                    request_fn,
                    "GET",
                    "/jobs/" + video_api.job_id(child_id),
                    timeout=15,
                )
            except Exception as exc:
                if _retryable_service_error(exc, 503):
                    time.sleep(max(poll_interval, 0.1))
                    continue
                raise
            status = str(child.get("status") or "")
            if get_short_job(job_id).get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)

            if status == "completed":
                result = child.get("result") or {}
                path = str(result.get("path") or "")
                if not path.endswith(".mp4"):
                    raise RuntimeError("completed video job has no MP4 path")

                latest = get_short_job(job_id)
                if latest.get("cancel_requested"):
                    return _finish_cancelled(job_id, request_fn)
                results = list(latest.get("scene_results") or [])
                if scene["id"] not in _completed_scene_ids(latest):
                    results.append({
                        "scene_id": scene["id"],
                        "duration": scene["duration"],
                        "status": "completed",
                        "video_job_id": child_id,
                        "path": path,
                    })
                _update_job(
                    job_id,
                    current_scene=scene_index + 1,
                    scene_results=results,
                    active_video_job_id=None,
                )
                continue

            if status == "failed":
                return _update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    error=str(child.get("error") or "video job failed"),
                    finished_at=time.time(),
                )

            if status == "cancelled":
                latest = get_short_job(job_id)
                if latest.get("cancel_requested"):
                    return _finish_cancelled(job_id, request_fn)
                return _update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    error="video job was cancelled unexpectedly",
                    finished_at=time.time(),
                )

            if status not in VIDEO_ACTIVE_STATUSES:
                raise RuntimeError(f"unknown video job status: {status or 'empty'}")

            if poll_interval:
                time.sleep(poll_interval)

    except Exception as exc:
        latest = get_short_job(job_id)
        if latest.get("cancel_requested"):
            return _finish_cancelled(job_id, request_fn)
        return _update_job(
            job_id,
            status="failed",
            phase="failed",
            error=str(exc),
            finished_at=time.time(),
        )


def _worker(job_id, request_fn, poll_interval):
    try:
        run_short_job(
            job_id,
            request_fn=request_fn,
            poll_interval=poll_interval,
        )
    finally:
        with _workers_lock:
            _workers.pop(job_id, None)


def start_short_job(job_id, *, request_fn=None, poll_interval=1.0):
    job_id = _job_id(job_id)
    get_short_job(job_id)
    with _workers_lock:
        existing = _workers.get(job_id)
        if existing is not None and existing.is_alive():
            return existing
        thread = threading.Thread(
            target=_worker,
            args=(job_id, request_fn, poll_interval),
            daemon=True,
            name=f"shorts-job-{job_id}",
        )
        _workers[job_id] = thread
        try:
            thread.start()
        except Exception:
            _workers.pop(job_id, None)
            raise
        return thread


def resume_short_jobs(*, request_fn=None, poll_interval=1.0):
    """Resume every durable non-terminal job, including its active child."""
    with _jobs_lock:
        jobs = _load_jobs()
    resumed = []
    for job in jobs.values():
        if job.get("status") in ACTIVE_STATUSES:
            start_short_job(
                job["id"],
                request_fn=request_fn,
                poll_interval=poll_interval,
            )
            resumed.append(job["id"])
    return resumed


def cancel_short_job(job_id, *, request_fn=None):
    job_id = _job_id(job_id)
    request_fn = request_fn or video_api.request
    job = get_short_job(job_id)
    if job.get("status") not in ACTIVE_STATUSES:
        raise ValueError("short job cannot be cancelled")
    _update_job(job_id, cancel_requested=True)
    return _finish_cancelled(job_id, request_fn)
