"""Retention helpers for Talking Photo results."""

from __future__ import annotations

from agent import media_lifecycle, talking_photo


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


def discard_job(job_id: str) -> dict:
    job = talking_photo.get_job(job_id)
    if job.get("status") in talking_photo.ACTIVE_STATUSES:
        talking_photo.cancel_job(job_id)
        return {"id": job_id, "status": "cancelling", "deleted": False}

    result = media_lifecycle.discard("talking_photo", job_id)
    if result.get("persistent"):
        return {"id": job_id, "status": "kept", **result}

    talking_photo._job_file(job_id).unlink(missing_ok=True)
    return {"id": job_id, "status": "discarded", **result}
