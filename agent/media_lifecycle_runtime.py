"""Runtime hook that tracks generated image/video outputs for cleanup."""

from __future__ import annotations

from copy import deepcopy
import threading
import time

from agent import batch_state
from agent import media_lifecycle
from agent import media_queue


_installed = False
_cleaner_started = False
_original_mirror_native = None


def _shorts_references_job(job_id: str) -> bool:
    """Return whether a queue job belongs to a durable Shorts project."""
    try:
        jobs = batch_state.load_jobs(media_queue.SHORTS_FILE)
    except Exception:
        return False
    for raw in jobs.values():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("active_video_job_id") or "") == job_id:
            return True
        for result in raw.get("scene_results") or []:
            if isinstance(result, dict) and str(result.get("video_job_id") or "") == job_id:
                return True
    return False


def _register_completed(job_id: str, job: dict) -> None:
    if not isinstance(job, dict) or job.get("status") != "completed":
        return
    kind = str(job.get("kind") or "")
    if kind not in {"image", "video"}:
        return
    result = job.get("result")
    if not isinstance(result, dict):
        return
    asset_id = str(result.get("id") or "")
    path = result.get("path")
    if not asset_id or not path:
        return

    chat_id = str(job.get("chat_id") or "")
    project_owned = (
        _shorts_references_job(job_id)
        or chat_id.startswith("shorts:")
        or chat_id.startswith("project:")
    )
    owner = "project" if project_owned else (
        "talking-photo-intermediate"
        if chat_id.startswith("talking-photo:")
        else "chat"
    )
    media_lifecycle.register(
        kind,
        asset_id,
        path,
        persistent=project_owned,
        owner=owner,
    )


def _wrapped_mirror_native(job_id, native):
    result = _original_mirror_native(job_id, native)
    try:
        _register_completed(str(job_id), deepcopy(result) if isinstance(result, dict) else {})
    except Exception:
        # Lifecycle bookkeeping must never turn a completed generation into a
        # failed media job. The TTL fallback can repair/clean later.
        pass
    return result


def _cleaner_loop() -> None:
    while True:
        time.sleep(60 * 60)
        try:
            media_lifecycle.cleanup_expired()
        except Exception:
            pass


def install_runtime() -> None:
    """Install queue tracking before the production Agent starts its worker."""
    global _installed, _cleaner_started, _original_mirror_native
    if _installed:
        return
    _original_mirror_native = media_queue._mirror_native
    media_queue._mirror_native = _wrapped_mirror_native
    _installed = True

    try:
        media_lifecycle.cleanup_expired()
    except Exception:
        pass

    if not _cleaner_started:
        thread = threading.Thread(
            target=_cleaner_loop,
            daemon=True,
            name="mlx-media-lifecycle-cleaner",
        )
        thread.start()
        _cleaner_started = True


def uninstall_runtime_for_tests() -> None:
    global _installed, _original_mirror_native
    if _installed and _original_mirror_native is not None:
        media_queue._mirror_native = _original_mirror_native
    _installed = False
    _original_mirror_native = None
