"""Opt-in Shorts runtime: Qwen image keyframes followed by LTX I2V.

The module patches only ``shorts_jobs.run_short_job``. Existing projects keep
using the original T2V worker because ``ShortProject.consistency_mode`` defaults
to false for compatibility. The production entrypoint installs the patch
before importing ``agent.app`` so startup recovery also follows this path.
"""

import time

from agent import image_api, shorts_jobs, video_api
from agent.shorts_consistency import (
    consistent_video_job_request,
    keyframe_job_request,
    scene_keyframe_prompt,
)
from agent.shorts_planner import ShortProject


IMAGE_ACTIVE_STATUSES = {
    "queued", "dispatching", "loading", "running", "saving",
}
VIDEO_ACTIVE_STATUSES = shorts_jobs.VIDEO_ACTIVE_STATUSES

_ORIGINAL_RUN_SHORT_JOB = None
_INSTALLED = False
_EDIT_CAPABILITY = {"checked_at": 0.0, "available": False}


def _uses_consistency(job):
    try:
        return ShortProject.model_validate(job["project"]).consistency_mode
    except Exception:
        return False


def _completed_keyframes(job):
    return {
        item.get("scene_id"): item
        for item in job.get("keyframe_results", [])
        if item.get("status") == "completed" and item.get("path")
    }


def _cancel_active_image(job):
    child_id = job.get("active_image_job_id")
    if not child_id:
        return
    try:
        image_api.request(
            "POST",
            "/jobs/" + image_api.job_id(child_id) + "/cancel",
            {},
            timeout=30,
        )
    except Exception:
        pass


def _finish_cancelled(job_id, video_request_fn):
    job = shorts_jobs.get_short_job(job_id)
    _cancel_active_image(job)
    return shorts_jobs._finish_cancelled(job_id, video_request_fn)


def _fail(job_id, error, child=None):
    from agent.shorts_diagnostics import failure_fields
    diagnosis = failure_fields(shorts_jobs.get_short_job(job_id), error, child)
    return shorts_jobs._update_job(
        job_id,
        status="failed",
        phase="failed",
        active_image_job_id=None,
        active_video_job_id=None,
        error=str(error),
        finished_at=time.time(),
        **diagnosis,
    )


def _image_request(method, path, payload=None, timeout=15):
    return image_api.request(method, path, payload, timeout=timeout)


def _video_request(request_fn, method, path, payload=None, timeout=15):
    return request_fn(method, path, payload, timeout=timeout)


def _image_edit_available():
    """Check for a ready local image-edit model, cached briefly per worker."""
    now = time.monotonic()
    if now - _EDIT_CAPABILITY["checked_at"] < 60:
        return _EDIT_CAPABILITY["available"]
    available = False
    try:
        data = _image_request("GET", "/models", timeout=5)
        for model in data.get("models", []):
            if (
                model.get("enabled")
                and model.get("available") is True
                and "image_edit" in (model.get("capabilities") or [])
            ):
                available = True
                break
    except Exception:
        available = False
    _EDIT_CAPABILITY.update(checked_at=now, available=available)
    return available


def _identity_anchor_path(project, keyframes, scene_index):
    if (
        scene_index <= 0
        or not project.character_consistency
        or not _image_edit_available()
    ):
        return None
    first_id = project.scenes[0].id
    anchor = keyframes.get(first_id)
    return anchor.get("path") if anchor else None


def run_consistent_short_job(
    job_id,
    *,
    request_fn=None,
    tts_request_fn=None,
    compose_fn=None,
    poll_interval=1.0,
):
    """Run/resume one consistency-mode job synchronously."""
    job_id = shorts_jobs._job_id(job_id)
    video_request_fn = request_fn or video_api.request
    job = shorts_jobs.get_short_job(job_id)

    if job.get("status") in shorts_jobs.TERMINAL_STATUSES:
        return job
    if job.get("cancel_requested"):
        return _finish_cancelled(job_id, video_request_fn)

    if job.get("status") in {"video_completed", "tts_completed"}:
        return _ORIGINAL_RUN_SHORT_JOB(
            job_id,
            request_fn=video_request_fn,
            tts_request_fn=tts_request_fn,
            compose_fn=compose_fn,
            poll_interval=poll_interval,
        )

    shorts_jobs._update_job(
        job_id,
        status="running",
        phase=job.get("phase") if job.get("phase") in {"keyframe", "video"} else "keyframe",
        started_at=job.get("started_at") or time.time(),
        error=None,
    )

    try:
        from agent.shorts_preflight import preflight_project
        readiness = preflight_project(ShortProject.model_validate(job['project']), request_fn=_image_request,
                                      scene_results=job.get('scene_results'), keyframe_results=job.get('keyframe_results'))
        shorts_jobs._update_job(job_id, warnings=readiness['warnings'], provider_preflight=readiness)
        while True:
            job = shorts_jobs.get_short_job(job_id)
            if job.get("status") in shorts_jobs.TERMINAL_STATUSES:
                return job
            if job.get("cancel_requested"):
                return _finish_cancelled(job_id, video_request_fn)

            project = ShortProject.model_validate(job["project"])
            if not project.consistency_mode:
                return _ORIGINAL_RUN_SHORT_JOB(
                    job_id,
                    request_fn=video_request_fn,
                    tts_request_fn=tts_request_fn,
                    compose_fn=compose_fn,
                    poll_interval=poll_interval,
                )

            completed_ids = shorts_jobs._completed_scene_ids(job)
            scene_index = 0
            while (
                scene_index < len(project.scenes)
                and project.scenes[scene_index].id in completed_ids
            ):
                scene_index += 1

            if scene_index >= len(project.scenes):
                shorts_jobs._update_job(
                    job_id,
                    status="video_completed",
                    phase="video_completed",
                    current_scene=len(project.scenes),
                    active_image_job_id=None,
                    active_video_job_id=None,
                    finished_at=None,
                    error=None,
                )
                return _ORIGINAL_RUN_SHORT_JOB(
                    job_id,
                    request_fn=video_request_fn,
                    tts_request_fn=tts_request_fn,
                    compose_fn=compose_fn,
                    poll_interval=poll_interval,
                )

            if scene_index != job.get("current_scene"):
                job = shorts_jobs._update_job(job_id, current_scene=scene_index)

            scene_model = project.scenes[scene_index]
            scene = scene_model.model_dump(mode="json")
            keyframes = _completed_keyframes(job)
            keyframe = keyframes.get(scene_model.id)

            if keyframe is None:
                anchor_path = (None if scene_model.id in job.get('anchor_fallback_scenes', [])
                               else _identity_anchor_path(project, keyframes, scene_index))
                if scene_index > 0 and project.character_consistency and not anchor_path:
                    warnings = list(dict.fromkeys([*(job.get('warnings') or []), 'character_anchor_fallback']))
                    shorts_jobs._update_job(job_id, warnings=warnings)
                child_id = job.get("active_image_job_id")
                if not child_id:
                    try:
                        request = keyframe_job_request(
                            job,
                            scene_model,
                            scene_index,
                            identity_anchor_path=anchor_path,
                        )
                        child = _image_request(
                            "POST", "/jobs", request, timeout=15,
                        )
                    except Exception as exc:
                        if shorts_jobs._retryable_service_error(exc, 409, 503):
                            time.sleep(max(poll_interval, 0.1))
                            continue
                        raise
                    child_id = image_api.job_id(child.get("id"))
                    job = shorts_jobs._update_job(
                        job_id,
                        active_image_job_id=child_id,
                        active_video_job_id=None,
                        phase="keyframe",
                        child_progress=0.,
                    )

                try:
                    child = _image_request(
                        "GET",
                        "/jobs/" + image_api.job_id(child_id),
                        timeout=15,
                    )
                except Exception as exc:
                    if shorts_jobs._retryable_service_error(exc, 503):
                        time.sleep(max(poll_interval, 0.1))
                        continue
                    raise
                status = str(child.get("status") or "")
                shorts_jobs._update_job(job_id, child_progress=child.get('progress') or 0.,
                                        active_provider=child.get('provider'), active_model=child.get('model'))
                if shorts_jobs.get_short_job(job_id).get("cancel_requested"):
                    return _finish_cancelled(job_id, video_request_fn)

                if status == "completed":
                    result = child.get("result") or {}
                    path = str(result.get("path") or "")
                    image_id = str(result.get("id") or "")
                    if not path.endswith(".png") or not image_id:
                        raise RuntimeError("completed keyframe job has no managed PNG result")

                    latest = shorts_jobs.get_short_job(job_id)
                    keyframe_results = list(latest.get("keyframe_results") or [])
                    existing_ids = {
                        item.get("scene_id")
                        for item in keyframe_results
                        if item.get("status") == "completed"
                    }
                    if scene_model.id not in existing_ids:
                        keyframe_results.append({
                            "scene_id": scene_model.id,
                            "status": "completed",
                            "image_job_id": child_id,
                            "image_id": image_id,
                            "path": path,
                            "prompt": scene_keyframe_prompt(
                                project,
                                scene_model,
                                scene_index,
                                identity_anchor=bool(anchor_path),
                            ),
                            "identity_anchor_path": anchor_path,
                        })
                    shorts_jobs._update_job(
                        job_id,
                        keyframe_results=keyframe_results,
                        active_image_job_id=None,
                        phase="video",
                    )
                    continue

                if status == "failed":
                    if anchor_path and child.get('error_code') == 'IMAGE_PROVIDER_INCOMPATIBLE':
                        shorts_jobs._update_job(job_id, active_image_job_id=None, child_progress=0.,
                            anchor_fallback_scenes=[*(job.get('anchor_fallback_scenes') or []), scene_model.id],
                            warnings=list(dict.fromkeys([*(job.get('warnings') or []), 'character_anchor_fallback'])))
                        continue
                    return _fail(job_id, child.get("error") or "keyframe job failed", child)
                if status == "cancelled":
                    latest = shorts_jobs.get_short_job(job_id)
                    if latest.get("cancel_requested"):
                        return _finish_cancelled(job_id, video_request_fn)
                    return _fail(job_id, "keyframe job was cancelled unexpectedly")
                if status not in IMAGE_ACTIVE_STATUSES:
                    return _fail(job_id, f"unknown image job status: {status or 'empty'}")

                if poll_interval:
                    time.sleep(poll_interval)
                continue

            child_id = job.get("active_video_job_id")
            if not child_id:
                try:
                    child = _video_request(
                        video_request_fn,
                        "POST",
                        "/jobs",
                        consistent_video_job_request(job, scene, keyframe["path"]),
                        timeout=15,
                    )
                except Exception as exc:
                    if shorts_jobs._retryable_service_error(exc, 409, 503):
                        time.sleep(max(poll_interval, 0.1))
                        continue
                    raise
                child_id = video_api.job_id(child.get("id"))
                job = shorts_jobs._update_job(
                    job_id,
                    active_video_job_id=child_id,
                    active_image_job_id=None,
                    phase="video",
                    child_progress=0.,
                )

            try:
                child = _video_request(
                    video_request_fn,
                    "GET",
                    "/jobs/" + video_api.job_id(child_id),
                    timeout=15,
                )
            except Exception as exc:
                if shorts_jobs._retryable_service_error(exc, 503):
                    time.sleep(max(poll_interval, 0.1))
                    continue
                raise
            status = str(child.get("status") or "")
            shorts_jobs._update_job(job_id, child_progress=child.get('progress') or 0.)
            if shorts_jobs.get_short_job(job_id).get("cancel_requested"):
                return _finish_cancelled(job_id, video_request_fn)

            if status == "completed":
                result = child.get("result") or {}
                path = str(result.get("path") or "")
                if not path.endswith(".mp4"):
                    raise RuntimeError("completed video job has no MP4 path")

                latest = shorts_jobs.get_short_job(job_id)
                results = list(latest.get("scene_results") or [])
                if scene_model.id not in shorts_jobs._completed_scene_ids(latest):
                    results.append({
                        "scene_id": scene_model.id,
                        "duration": scene_model.duration,
                        "status": "completed",
                        "video_job_id": child_id,
                        "path": path,
                        "keyframe_image_id": keyframe.get("image_id"),
                        "keyframe_path": keyframe.get("path"),
                    })
                shorts_jobs._update_job(
                    job_id,
                    current_scene=scene_index + 1,
                    scene_results=results,
                    active_video_job_id=None,
                    phase="keyframe",
                )
                continue

            if status == "failed":
                return _fail(job_id, child.get("error") or "video job failed", child)
            if status == "cancelled":
                latest = shorts_jobs.get_short_job(job_id)
                if latest.get("cancel_requested"):
                    return _finish_cancelled(job_id, video_request_fn)
                return _fail(job_id, "video job was cancelled unexpectedly")
            if status not in VIDEO_ACTIVE_STATUSES:
                return _fail(job_id, f"unknown video job status: {status or 'empty'}")

            if poll_interval:
                time.sleep(poll_interval)

    except Exception as exc:
        latest = shorts_jobs.get_short_job(job_id)
        if latest.get("cancel_requested"):
            return _finish_cancelled(job_id, video_request_fn)
        return _fail(job_id, exc)


def _patched_run_short_job(job_id, **kwargs):
    job = shorts_jobs.get_short_job(job_id)
    if _uses_consistency(job):
        return run_consistent_short_job(job_id, **kwargs)
    return _ORIGINAL_RUN_SHORT_JOB(job_id, **kwargs)


def install_runtime():
    """Install the compatibility-preserving runtime patch exactly once."""
    global _INSTALLED, _ORIGINAL_RUN_SHORT_JOB
    if _INSTALLED:
        return
    _ORIGINAL_RUN_SHORT_JOB = shorts_jobs.run_short_job
    shorts_jobs.run_short_job = _patched_run_short_job
    _INSTALLED = True
