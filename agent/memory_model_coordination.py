"""Private coordination of 4B inference with memory-hungry media jobs.

No prompts, personal content, or model output in marker files. A cross-process
shared lock protects an active memory request from supervisor termination.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import time

ROOT = Path.home() / ".config/mlx-web/memory-model-control"
STATE = ROOT / "state.json"
DEMAND = ROOT / "media-demand.json"
ROUTER_DEMAND = ROOT / "router-demand.json"
INFERENCE_DEMAND = ROOT / "inference-demand.json"
ON_DEMAND = ROOT / "on-demand.json"
MEMORY_DB = Path.home() / ".config/mlx-web/personal-memory.sqlite3"
MEMORY_CONTROL = Path.home() / ".config/mlx-web/memory-control.json"
LOCK = ROOT / "inference.lock"
MEDIA_JOB_FILE = Path.home() / ".config/mlx-web/media-queue/jobs.json"
TERMINAL = {"completed", "failed", "cancelled"}
HEARTBEAT_SECONDS = 30
DEMAND_SECONDS = 45


class DeferredMemoryInference(RuntimeError):
    """Transient scheduling deferral: do NOT mark the SQLite job failed."""


class UnmanagedMemoryModel(RuntimeError):
    """A configured external 4B process cannot be safely stopped by Nobby."""


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


def note_media_demand(kind, *, exclusive=False):
    if kind not in ("image", "video"):
        raise ValueError("Unsupported media kind")
    _write(DEMAND, {
        "kind": kind,
        "until": time.time() + DEMAND_SECONDS,
        "exclusive": bool(exclusive),
    })


def on_demand_enabled():
    """Explicitly opted-in owner-only policy; absent means legacy behavior."""
    return _read(ON_DEMAND).get("enabled") is True


def request_router_demand(*, seconds=150):
    """Request the *same* supervised 4B for a short router inference.

    No messages, private data, or model output enter the owner-only marker.
    New router requests cannot outrank active/pending image/video jobs.
    """
    if active_media_kind():
        raise DeferredMemoryInference("Router deferred during exclusive media")
    _write(ROUTER_DEMAND, {
        "until": time.time() + max(1, min(float(seconds), 300)),
    })


def request_memory_demand(*, seconds=240):
    """Wake the shared 4B for an actual extraction, not an idle chat tab."""
    if active_media_kind():
        raise DeferredMemoryInference("Memory extraction deferred for media")
    _write(INFERENCE_DEMAND, {
        "until": time.time() + max(1, min(float(seconds), 300)),
    })


def memory_demand_active():
    marker = _read(INFERENCE_DEMAND)
    until = marker.get("until")
    return type(until) in (int, float) and time.time() < until <= time.time() + 310


def release_router_demand():
    """Drop warm-start demand after router use; running inference keeps its lock."""
    _write(ROUTER_DEMAND, {"until": 0})


def release_memory_demand():
    """Start the 120-second idle grace after a completed extraction request."""
    _write(INFERENCE_DEMAND, {"until": 0})


def router_demand_active():
    marker = _read(ROUTER_DEMAND)
    until = marker.get("until")
    return type(until) in (int, float) and time.time() < until <= time.time() + 310


def pending_extraction_work():
    """Read-only durable job check. No schema changes or private text reads.

    SQLite WAL readers see committed work. A temporarily unreadable database
    causes a retry on the supervisor's next tick, never a job deletion.
    """
    if not MEMORY_DB.is_file():
        return False
    try:
        pause = _read(MEMORY_CONTROL)
        if pause.get("paused") is True:
            return False
        uri = MEMORY_DB.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.3) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='smart_learning'"
            ).fetchone()
            if row is None or row[0] != "1":
                return False
            return conn.execute(
                "SELECT EXISTS(SELECT 1 FROM analysis_jobs "
                "WHERE status='pending' LIMIT 1)"
            ).fetchone()[0] == 1
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def requested_media_priority():
    marker = _read(DEMAND)
    if (marker.get("kind") in ("image", "video")
            and type(marker.get("until")) in (float, int)
            and marker["until"] > time.time()):
        return marker["kind"]
    return None


def exclusive_media_requested(kind):
    """Only a fresh, explicit queue request may preempt a healthy 4B model."""
    marker = _read(DEMAND)
    return (kind in ("image", "video")
            and marker.get("kind") == kind
            and marker.get("exclusive") is True
            and type(marker.get("until")) in (float, int)
            and marker["until"] > time.time())


def active_media_kind():
    if (kind := requested_media_priority()):
        return kind
    # Native /generate, /edit, /upscale and /jobs can bypass Agent's
    # persistent media queue. Keep the 4B supervisor suspended for the
    # ENTIRE active image/video lease, not only the 45-second demand marker.
    # A live PID and the existing cross-process lease record are required.
    try:
        import runtime_coordinator as rc
        holder = rc.lease_state_snapshot().get("active")
        if holder and holder.get("workload") in ("image", "video"):
            return holder["workload"]
    except (OSError, ValueError):
        pass
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


def _external_dedicated_model_running():
    """Probe only the explicitly configured local memory-model port.

    We never terminate a manually launched or unknown process. If a dedicated
    4B is externally managed, exclusive GPU media cannot claim it was released.
    A quick loopback TCP check works even if the model API is busy loading.
    """
    import socket
    from agent import dedicated_memory_model
    try:
        config = dedicated_memory_model.settings()
        if config.get("mode") != "dedicated":
            return False
        with socket.create_connection(("127.0.0.1", config["port"]), timeout=0.4):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def prepare_media_dispatch(kind, timeout_seconds=20, *, exclusive=False):
    """Wait for a supervisor-owned 4B to finish its current inference and exit.

    In exclusive mode, any configured manually owned 4B blocks dispatch with
    an actionable error. Neither the supervisor nor media dispatch may kill
    foreign PIDs; nonexclusive callers retain their former compatibility.
    """
    if kind not in ("image", "video"):
        raise ValueError("Unsupported media kind")
    state = supervisor_state()
    if not state.get("owned"):
        if exclusive and (state.get("state") == "external" or _external_dedicated_model_running()):
            raise UnmanagedMemoryModel(
                "Exklusiver Medienmodus: Ein extern gestartetes 4B-Memory-Modell "
                "ist aktiv. Bitte den manuell gestarteten 4B-Server beenden "
                "oder vom MLX-Nobby-Supervisor verwalten lassen."
            )
        return True
    if not exclusive:
        import runtime_coordinator as rc
        try:
            snapshot = rc.memory_budget_snapshot()
            reserve = rc.model_load_reserve_gb(kind)
            target_headroom = rc.VIDEO_MIN_HEADROOM_GB if kind == "video" else rc.MEDIA_MIN_HEADROOM_GB
        except (OSError, RuntimeError, ValueError):
            return True  # Native media admission remains authoritative on probe errors.
        if not (rc.memory_relief_needed(snapshot, min_headroom_gb=target_headroom)
                or rc.projected_memory_hard_limit_reached(snapshot, reserve)):
            return True
    note_media_demand(kind, exclusive=exclusive)
    deadline = time.monotonic() + max(0, timeout_seconds)
    while time.monotonic() < deadline:
        state = supervisor_state()
        if not state.get("owned"):
            if exclusive and _external_dedicated_model_running():
                raise UnmanagedMemoryModel(
                    "Exklusiver Medienmodus: 4B läuft weiterhin außerhalb "
                    "des Supervisors. Beende den externen Modellserver."
                )
            return True
        time.sleep(0.4)
    return False  # Durable Agent queue retries; native routes fail safely.
