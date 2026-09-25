"""Persistent, resumable orchestration of ShortProject video scenes."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from agent import batch_state, service_proxy, video_api
from agent.shorts_planner import ShortProject


SHORTS_DIRECTORY = Path.home() / ".config/mlx-web/shorts"
SHORTS_JOBS_FILE = SHORTS_DIRECTORY / "jobs.json"
SHORT_JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
ACTIVE_STATUSES = {"queued", "running", "video_completed"}
TERMINAL_STATUSES = {"tts_completed", "failed", "cancelled"}
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
        "tts_status": "pending",
        "tts_path": None,
        "tts_started_at": None,
        "tts_finished_at": None,
        "tts_metadata": None,
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


def _request_tts(payload):
    url = os.environ.get(
        "SPEECH_SERVICE_URL", "http://127.0.0.1:8050",
    ).rstrip("/") + "/v1/audio/speech"
    response = service_proxy.forward(
        url,
        json.dumps(payload).encode("utf-8"),
        timeout=900,
    )
    if response.status_code >= 400:
        detail = bytes(response.body or b"").decode(
            "utf-8", errors="replace",
        )
        raise RuntimeError(detail[:2000] or "speech service failed")
    audio = bytes(response.body or b"")
    if not audio:
        raise RuntimeError("speech service returned empty audio")
    return audio


def narration_for_project(project):
    if not isinstance(project, ShortProject):
        project = ShortProject.model_validate(project)
    return "\n\n".join(scene.narration for scene in project.scenes)


def _tts_output_path(job_id):
    return SHORTS_DIRECTORY / job_id / "voiceover.mp3"


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
        if job.get("status") == "tts_completed":
            return deepcopy(job)
        job.update(
            cancel_requested=True,
            status="cancelled",
            phase="cancelled",
            tts_status=(
                "cancelled"
                if job.get("tts_status") != "completed"
                else "completed"
            ),
            tts_finished_at=(
                job.get("tts_finished_at") or time.time()
            ),
            finished_at=time.time(),
            error=None,
        )
        jobs[job_id] = job
        _save_jobs(jobs)
        return deepcopy(job)


def _run_tts(job_id, request_fn, tts_request_fn):
    job = get_short_job(job_id)
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    existing_path = Path(str(job.get("tts_path") or _tts_output_path(job_id)))
    if existing_path.is_file() and existing_path.stat().st_size > 0:
        project = ShortProject.model_validate(job["project"])
        narration = narration_for_project(project)
        finished_at = job.get("tts_finished_at") or time.time()
        return _update_job(
            job_id,
            status="tts_completed",
            phase="tts_completed",
            tts_status="completed",
            tts_path=str(existing_path),
            tts_finished_at=finished_at,
            tts_metadata=job.get("tts_metadata") or {
                "mime_type": "audio/mpeg",
                "language": project.language,
                "scene_count": len(project.scenes),
                "narration_characters": len(narration),
            },
            finished_at=job.get("finished_at") or finished_at,
            error=None,
        )

    project = ShortProject.model_validate(job["project"])
    if not project.voice_enabled:
        now = time.time()
        return _update_job(
            job_id,
            status="tts_completed",
            phase="tts_completed",
            tts_status="disabled",
            tts_finished_at=now,
            tts_metadata={
                "language": project.language,
                "scene_count": len(project.scenes),
                "disabled": True,
            },
            finished_at=now,
            error=None,
        )

    started_at = job.get("tts_started_at") or time.time()
    _update_job(
        job_id,
        status="running",
        phase="tts",
        tts_status="running",
        tts_started_at=started_at,
        error=None,
    )
    narration = narration_for_project(project)
    audio = tts_request_fn({
        "input": narration,
        "language": project.language,
    })
    if not isinstance(audio, bytes) or not audio:
        raise RuntimeError("speech service returned invalid audio")

    if get_short_job(job_id).get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    output_path = _tts_output_path(job_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch_state.atomic_write_with(
        output_path,
        lambda temporary: temporary.write_bytes(audio),
    )

    if get_short_job(job_id).get("cancel_requested"):
        output_path.unlink(missing_ok=True)
        return _finish_cancelled(job_id, request_fn)

    finished_at = time.time()
    return _update_job(
        job_id,
        status="tts_completed",
        phase="tts_completed",
        tts_status="completed",
        tts_path=str(output_path),
        tts_finished_at=finished_at,
        tts_metadata={
            "mime_type": "audio/mpeg",
            "language": project.language,
            "scene_count": len(project.scenes),
            "narration_characters": len(narration),
        },
        finished_at=finished_at,
        error=None,
    )


def run_short_job(
    job_id,
    *,
    request_fn=None,
    tts_request_fn=None,
    poll_interval=1.0,
):
    """Run or resume one job synchronously; workers call this in a thread."""
    job_id = _job_id(job_id)
    request_fn = request_fn or video_api.request
    tts_request_fn = tts_request_fn or _request_tts
    job = get_short_job(job_id)
    if job.get("status") in TERMINAL_STATUSES:
        return job
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, request_fn)

    if job.get("status") == "video_completed":
        try:
            return _run_tts(job_id, request_fn, tts_request_fn)
        except Exception as exc:
            latest = get_short_job(job_id)
            if latest.get("cancel_requested"):
                return _finish_cancelled(job_id, request_fn)
            return _update_job(
                job_id,
                status="failed",
                phase="failed",
                tts_status="failed",
                error=str(exc),
                tts_finished_at=time.time(),
                finished_at=time.time(),
            )

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
                _update_job(
                    job_id,
                    status="video_completed",
                    phase="video_completed",
                    current_scene=len(project.scenes),
                    active_video_job_id=None,
                    finished_at=None,
                    error=None,
                )
                return _run_tts(job_id, request_fn, tts_request_fn)

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
        changes = {
            "status": "failed",
            "phase": "failed",
            "error": str(exc),
            "finished_at": time.time(),
        }
        if get_short_job(job_id).get("phase") == "tts":
            changes.update(
                tts_status="failed",
                tts_finished_at=time.time(),
            )
        return _update_job(
            job_id,
            **changes,
        )


def _worker(job_id, request_fn, tts_request_fn, poll_interval):
    try:
        run_short_job(
            job_id,
            request_fn=request_fn,
            tts_request_fn=tts_request_fn,
            poll_interval=poll_interval,
        )
    finally:
        with _workers_lock:
            _workers.pop(job_id, None)


def start_short_job(
    job_id,
    *,
    request_fn=None,
    tts_request_fn=None,
    poll_interval=1.0,
):
    job_id = _job_id(job_id)
    get_short_job(job_id)
    with _workers_lock:
        existing = _workers.get(job_id)
        if existing is not None and existing.is_alive():
            return existing
        thread = threading.Thread(
            target=_worker,
            args=(job_id, request_fn, tts_request_fn, poll_interval),
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


def resume_short_jobs(
    *,
    request_fn=None,
    tts_request_fn=None,
    poll_interval=1.0,
):
    """Resume every durable non-terminal job, including its active child."""
    with _jobs_lock:
        jobs = _load_jobs()
    resumed = []
    for job in jobs.values():
        if job.get("status") in ACTIVE_STATUSES:
            start_short_job(
                job["id"],
                request_fn=request_fn,
                tts_request_fn=tts_request_fn,
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
