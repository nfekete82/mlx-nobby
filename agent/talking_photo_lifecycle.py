"""Retention helpers for Talking Photo results."""

from __future__ import annotations

import threading
import time

from agent import media_lifecycle, talking_photo


_DISCARD_WAIT_SECONDS = 30 * 60
_DISCARD_POLL_SECONDS = 0.25


def _register_completed(job_id: str, job: dict | None = None) -> dict:
    job = talking_photo.get_job(job_id) if job is None else job
    if job.get("status") != "completed":
        return job
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    if path.is_file():
        record = media_lifecycle.register(
            "talking_photo",
            job_id,
            path,
            persistent=bool(job.get("saved")),
            owner="talking-photo",
        )
        job = dict(job)
        job["temporary"] = not bool(record.get("persistent"))
    return job


def get_job(job_id: str) -> dict:
    return _register_completed(job_id)


def keep_job(job_id: str) -> dict:
    job = talking_photo.get_job(job_id)
    if job.get("status") != "completed":
        raise ValueError("Talking Photo ist noch nicht fertig")
    _register_completed(job_id, job)
    record = media_lifecycle.persist("talking_photo", job_id)
    with talking_photo._jobs_lock:
        current = talking_photo._read_job(job_id)
        current["saved"] = True
        talking_photo._write_job(current)
    return {
        "id": job_id,
        "saved": True,
        "persistent": bool(record.get("persistent")),
    }


def _discard_terminal(job_id: str, job: dict) -> dict:
    if job.get("status") == "completed":
        # Register here as well as in GET polling so a completion/close race is
        # immediately deletable instead of waiting for the TTL sweeper.
        _register_completed(job_id, job)

    result = media_lifecycle.discard("talking_photo", job_id)
    if result.get("persistent"):
        return {"id": job_id, "status": "kept", **result}

    # Failed/cancelled jobs normally have no output. If an encoder left one
    # behind, remove it because this job was explicitly discarded.
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    path.unlink(missing_ok=True)
    try:
        media_lifecycle.forget("talking_photo", job_id)
    except (ValueError, OSError):
        pass
    talking_photo._job_file(job_id).unlink(missing_ok=True)
    return {"id": job_id, "status": "discarded", **result}


def _discard_when_terminal(job_id: str) -> None:
    deadline = time.monotonic() + _DISCARD_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            job = talking_photo.get_job(job_id)
        except Exception:
            return
        if job.get("status") in talking_photo.TERMINAL_STATUSES:
            try:
                _discard_terminal(job_id, job)
            except Exception:
                pass
            return
        time.sleep(_DISCARD_POLL_SECONDS)


def discard_job(job_id: str) -> dict:
    job = talking_photo.get_job(job_id)
    if job.get("status") in talking_photo.ACTIVE_STATUSES:
        talking_photo.cancel_job(job_id)
        thread = threading.Thread(
            target=_discard_when_terminal,
            args=(job_id,),
            daemon=True,
            name=f"talking-photo-discard-{job_id}",
        )
        thread.start()
        return {"id": job_id, "status": "cancelling", "deleted": False}

    return _discard_terminal(job_id, job)
