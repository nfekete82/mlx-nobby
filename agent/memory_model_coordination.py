"""Private coordination of 4B inference with memory-hungry media jobs.

No prompts, personal content, or model output in marker files. A cross-process
shared lock protects an active memory request from supervisor termination.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path.home() / ".config/mlx-web/memory-model-control"
STATE = ROOT / "state.json"
DEMAND = ROOT / "media-demand.json"
LOCK = ROOT / "inference.lock"
MEDIA_JOB_FILE = Path.home() / ".config/mlx-web/media-queue/jobs.json"
TERMINAL = {"completed", "failed", "cancelled"}
HEARTBEAT_SECONDS = 30
DEMAND_SECONDS = 45


class DeferredMemoryInference(RuntimeError):
    """Transient scheduling deferral: do NOT mark the SQLite job failed."""


def _write(path: Path, data: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(data, out, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(filename, path)
    finally:
        try:
            os.unlink(filename)
        except FileNotFoundError:
            pass


def _read(path: Path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return result if isinstance(result, dict) else {}


def supervisor_state():
    result = _read(STATE)
    stamp = result.get("updated_at")
    if type(stamp) not in (float, int) or not 0 <= time.time() - stamp <= HEARTBEAT_SECONDS:
        return {}
    return result


def note_media_demand(kind):
    if kind not in ("image", "video"):
        raise ValueError("Unsupported media kind")
    _write(DEMAND, {"kind": kind, "until": time.time() + DEMAND_SECONDS})


def requested_media_priority():
    marker = _read(DEMAND)
    if (marker.get("kind") in ("image", "video")
            and type(marker.get("until")) in (float, int)
            and marker["until"] > time.time()):
        return marker["kind"]
    return None


def active_media_kind():
    if (kind := requested_media_priority()):
        return kind
    jobs = _read(MEDIA_JOB_FILE)
    active = [
        job.get("kind")
        for job in jobs.values()
        if isinstance(job, dict)
        and job.get("kind") in ("image", "video")
        and job.get("status") not in TERMINAL
        and (job.get("native_job_id") or job.get("status") == "dispatching")
    ]
    return "video" if "video" in active else ("image" if "image" in active else None)


@contextmanager
def inference_lease():
    """Keep 4B alive throughout a request; stop only after its checkpoint."""
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        state = supervisor_state()
        if state and requested_media_priority():
            raise DeferredMemoryInference("Memory extraction deferred for RAM preemption")
        if state.get("pause_extraction"):
            raise DeferredMemoryInference("Memory extraction deferred for RAM")
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def prepare_media_dispatch(kind, timeout_seconds=20):
    """Request RAM relief before native dispatch, preserving its own guard.

    A missing supervisor keeps previous service behavior. External manually
    launched port 8011 is never killed or assumed to be managed.
    """
    state = supervisor_state()
    if not state or state.get("state") in ("external", "disabled") or not state.get("owned"):
        return True
    import runtime_coordinator as rc
    try:
        snapshot = rc.memory_budget_snapshot()
        reserve = rc.model_load_reserve_gb(kind)
        target_headroom = rc.VIDEO_MIN_HEADROOM_GB if kind == "video" else rc.MEDIA_MIN_HEADROOM_GB
    except (OSError, RuntimeError, ValueError):
        return True  # Native media admission is authoritative if probe fails.
    if not (rc.memory_relief_needed(snapshot, min_headroom_gb=target_headroom)
            or rc.projected_memory_hard_limit_reached(snapshot, reserve)):
        return True
    note_media_demand(kind)
    deadline = time.monotonic() + max(0, timeout_seconds)
    while time.monotonic() < deadline:
        state = supervisor_state()
        if not state or not state.get("owned"):
            return True
        time.sleep(0.4)
    return False  # Caller retries its durable queued media request.
