"""Low-overhead health snapshot builder for System Health v1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
import threading
import time


CACHE_TTL_SECONDS = max(
    0.1,
    float(os.environ.get("MLX_SYSTEM_HEALTH_CACHE_SECONDS", "0.75")),
)

_cache_lock = threading.Lock()
_cached_snapshot: dict | None = None
_cached_at = 0.0
_installed = False


def invalidate() -> None:
    global _cached_snapshot, _cached_at
    with _cache_lock:
        _cached_snapshot = None
        _cached_at = 0.0


def _build_snapshot(health_module) -> dict:
    specs = tuple(health_module.SERVICE_SPECS)
    workers = max(1, min(len(specs), 8))

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="mlx-health",
    ) as pool:
        services = list(pool.map(health_module._service_snapshot, specs))

    queue_snapshot = health_module.media_queue.snapshot(limit=40)
    stuck_jobs = health_module._observe_stuck_jobs(queue_snapshot)
    healthy = sum(service["status"] == "healthy" for service in services)
    rss_total = sum(int(service.get("rss_bytes") or 0) for service in services)

    return {
        "ok": healthy == len(services) and not stuck_jobs,
        "version": 1,
        "checked_at": time.time(),
        "stuck_threshold_seconds": health_module.STUCK_SECONDS,
        "summary": {
            "healthy": healthy,
            "total": len(services),
            "degraded": sum(
                service["status"] == "degraded" for service in services
            ),
            "down": sum(service["status"] == "down" for service in services),
            "tracked_rss_bytes": rss_total,
            "active_media_jobs": int(queue_snapshot.get("active_count") or 0),
            "waiting_media_jobs": int(queue_snapshot.get("waiting_count") or 0),
            "stuck_jobs": len(stuck_jobs),
        },
        "services": services,
        "stuck_jobs": stuck_jobs,
        "media_queue": {
            "active_count": int(queue_snapshot.get("active_count") or 0),
            "waiting_count": int(queue_snapshot.get("waiting_count") or 0),
            "runtime": queue_snapshot.get("runtime") or {},
        },
    }


def _cached_builder(health_module):
    def build_health_snapshot() -> dict:
        global _cached_snapshot, _cached_at

        now = time.monotonic()
        with _cache_lock:
            if (
                _cached_snapshot is not None
                and now - _cached_at < CACHE_TTL_SECONDS
            ):
                return deepcopy(_cached_snapshot)

            snapshot = _build_snapshot(health_module)
            _cached_snapshot = deepcopy(snapshot)
            _cached_at = time.monotonic()
            return snapshot

    return build_health_snapshot


def install() -> None:
    """Replace the expensive sequential builder with a cached parallel one."""
    global _installed
    if _installed:
        return

    from agent import system_health_routes as health_module

    health_module.build_health_snapshot = _cached_builder(health_module)
    health_module.invalidate_health_cache = invalidate
    _installed = True
