"""Persistence optimizations for the durable media queue."""

from __future__ import annotations

import os
import time


PROGRESS_PERSIST_INTERVAL = max(
    0.25,
    float(os.environ.get("MLX_MEDIA_QUEUE_PROGRESS_PERSIST_SECONDS", "1.5")),
)
VOLATILE_PROGRESS_KEYS = frozenset({
    "progress",
    "current_step",
    "total_steps",
})

_last_progress_persist_at: dict[str, float] = {}
_installed = False


def reset_state() -> None:
    _last_progress_persist_at.clear()


def _changed_values(job: dict, changes: dict) -> dict:
    return {
        key: value
        for key, value in changes.items()
        if job.get(key) != value
    }


def _requires_immediate_persist(changed: dict) -> bool:
    return bool(set(changed) - VOLATILE_PROGRESS_KEYS)


def _optimized_update(media_module):
    def update(job_id, **changes):
        with media_module._jobs_lock:
            media_module._ensure_loaded_locked()
            job = media_module._jobs.get(job_id)
            if job is None:
                return None

            if job.get("status") in media_module.TERMINAL:
                requested = changes.get("status")
                if requested is not None and requested != job.get("status"):
                    return media_module._public(job)

            changed = _changed_values(job, changes)
            if not changed:
                return media_module._public(job)

            job.update(changed)

            now = time.monotonic()
            persist_now = _requires_immediate_persist(changed)

            if not persist_now:
                last_persist = _last_progress_persist_at.get(job_id, 0.0)
                persist_now = (
                    last_persist == 0.0
                    or now - last_persist >= PROGRESS_PERSIST_INTERVAL
                )

            if persist_now:
                media_module._persist_locked()
                _last_progress_persist_at[job_id] = now

            if job.get("status") in media_module.TERMINAL:
                _last_progress_persist_at.pop(job_id, None)

            return media_module._public(job)

    return update


def install() -> None:
    """Install the optimized update path without changing queue semantics."""
    global _installed
    if _installed:
        return

    from agent import media_queue

    media_queue._update = _optimized_update(media_queue)
    _installed = True
