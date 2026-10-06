"""Deterministic serialization and handoff for heavy local runtimes."""

import fcntl
import http.client
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
from contextlib import contextmanager
from pathlib import Path


IMAGE_URL = os.environ.get(
    "IMAGE_SERVICE_URL", "http://127.0.0.1:8030"
).rstrip("/")
VIDEO_URL = os.environ.get(
    "VIDEO_SERVICE_URL", "http://127.0.0.1:8060"
).rstrip("/")
LOCK_PATH = Path(os.environ.get(
    "MLX_RUNTIME_COORDINATOR_LOCK",
    f"/tmp/mlx-web-runtime-{os.getuid()}.lock",
))
STATE_DIR = Path(os.environ.get(
    "MLX_RUNTIME_COORDINATOR_STATE_DIR",
    f"/tmp/mlx-web-runtime-{os.getuid()}.d",
))
PROJECT_DIR = Path(__file__).resolve().parent
MLX_MANAGER = PROJECT_DIR / "scripts" / "mlx"
MLX_SERVER_LABEL = "de.nobby.mlx-server"
POLL_INTERVAL = 0.2
_PROCESS_LOCK = threading.RLock()
_LEASE_STATE = threading.local()


def _float_env(name, default):
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = float(default)
    return max(0.0, value)


MEMORY_RESERVE_GB = _float_env("MLX_RUNTIME_MEMORY_RESERVE_GB", 6.0)
MEDIA_MIN_HEADROOM_GB = _float_env("MLX_RUNTIME_MEDIA_HEADROOM_GB", 4.0)
VIDEO_MIN_HEADROOM_GB = _float_env("MLX_RUNTIME_VIDEO_HEADROOM_GB", 14.0)
PRESSURE_ELEVATED_FREE_PERCENT = _float_env(
    "MLX_RUNTIME_PRESSURE_ELEVATED_PERCENT", 18.0
)
PRESSURE_CRITICAL_FREE_PERCENT = _float_env(
    "MLX_RUNTIME_PRESSURE_CRITICAL_PERCENT", 8.0
)
HARD_MEMORY_USED_PERCENT = min(
    99.0,
    max(50.0, _float_env("MLX_RUNTIME_HARD_USED_PERCENT", 90.0)),
)

MODEL_LOAD_RESERVE_GB = {
    "chat": _float_env("MLX_RUNTIME_CHAT_LOAD_RESERVE_GB", 18.0),
    "router": _float_env("MLX_RUNTIME_ROUTER_LOAD_RESERVE_GB", 4.0),
    "image": _float_env("MLX_RUNTIME_IMAGE_LOAD_RESERVE_GB", 18.0),
    "image-upscale": _float_env("MLX_RUNTIME_IMAGE_UPSCALE_LOAD_RESERVE_GB", 2.0),
    "video": _float_env("MLX_RUNTIME_VIDEO_LOAD_RESERVE_GB", 20.0),
    "embedding": _float_env("MLX_RUNTIME_EMBEDDING_LOAD_RESERVE_GB", 4.0),
    "speech-stt": _float_env("MLX_RUNTIME_SPEECH_STT_LOAD_RESERVE_GB", 4.0),
    "speech-tts": _float_env("MLX_RUNTIME_SPEECH_TTS_LOAD_RESERVE_GB", 3.0),
    "speech-tts-clone": _float_env(
        "MLX_RUNTIME_SPEECH_TTS_CLONE_LOAD_RESERVE_GB", 3.0
    ),
    "vision-classifier": _float_env(
        "MLX_RUNTIME_VISION_CLASSIFIER_LOAD_RESERVE_GB", 0.5
    ),
}


class CoordinationCancelled(RuntimeError):
    """Raised when a queued handoff is cancelled by its owning job."""


class ServiceUnavailable(RuntimeError):
    """Raised when coordinator state cannot be read from a local service."""


def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _check_cancelled(cancel_event):
    if _cancelled(cancel_event):
        raise CoordinationCancelled("Runtime handoff was cancelled")


def _run_text(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def memory_budget_snapshot():
    """Return a conservative Apple-unified-memory budget snapshot.

    The value reported by ``memory_pressure`` is intentionally treated as an
    availability estimate rather than exact free RAM. macOS can reclaim caches
    and compressed pages, so this is a scheduling signal, not an accounting
    total.
    """
    total_bytes = None
    total_raw = _run_text(["sysctl", "-n", "hw.memsize"])
    try:
        total_bytes = int(total_raw) if total_raw else None
    except ValueError:
        total_bytes = None

    free_percent = None
    pressure_raw = _run_text(["memory_pressure"], timeout=10)
    match = re.search(
        r"System-wide memory free percentage:\s*([0-9.]+)%",
        pressure_raw,
    )
    if match:
        free_percent = max(0.0, min(100.0, float(match.group(1))))

    swap_used_gb = 0.0
    swap_total_gb = 0.0
    swap_raw = _run_text(["sysctl", "-n", "vm.swapusage"])
    total_match = re.search(r"total = ([0-9.]+)([MG])", swap_raw)
    used_match = re.search(r"used = ([0-9.]+)([MG])", swap_raw)

    def to_gb(match_value):
        if not match_value:
            return 0.0
        value = float(match_value.group(1))
        return value / 1024 if match_value.group(2) == "M" else value

    swap_total_gb = to_gb(total_match)
    swap_used_gb = to_gb(used_match)

    total_gb = (
        total_bytes / (1024 ** 3)
        if total_bytes is not None
        else None
    )
    available_gb = (
        total_gb * free_percent / 100
        if total_gb is not None and free_percent is not None
        else None
    )
    used_gb = (
        max(0.0, total_gb - available_gb)
        if total_gb is not None and available_gb is not None
        else None
    )
    reserve_gb = (
        min(MEMORY_RESERVE_GB, total_gb * 0.25)
        if total_gb is not None
        else MEMORY_RESERVE_GB
    )
    headroom_gb = (
        max(0.0, available_gb - reserve_gb)
        if available_gb is not None
        else None
    )

    if free_percent is None:
        pressure = "unknown"
    elif free_percent <= PRESSURE_CRITICAL_FREE_PERCENT:
        pressure = "critical"
    elif free_percent <= PRESSURE_ELEVATED_FREE_PERCENT:
        pressure = "elevated"
    else:
        pressure = "normal"

    def rounded(value):
        return round(value, 2) if value is not None else None

    return {
        "total_gb": rounded(total_gb),
        "available_estimate_gb": rounded(available_gb),
        "used_estimate_gb": rounded(used_gb),
        "free_percent": rounded(free_percent),
        "reserve_gb": rounded(reserve_gb),
        "headroom_gb": rounded(headroom_gb),
        "swap_total_gb": rounded(swap_total_gb),
        "swap_used_gb": rounded(swap_used_gb),
        "pressure": pressure,
    }


def memory_relief_needed(snapshot, min_headroom_gb=MEDIA_MIN_HEADROOM_GB):
    """Return whether a heavy media job should release the chat runtime first."""
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("pressure") in {"elevated", "critical"}:
        return True
    headroom = snapshot.get("headroom_gb")
    if isinstance(headroom, (int, float)) and not isinstance(headroom, bool):
        return float(headroom) < float(min_headroom_gb)
    return False


def memory_hard_limit_reached(snapshot):
    """Return whether starting another heavy runtime would be unsafe."""
    if not isinstance(snapshot, dict):
        return False

    free_percent = snapshot.get("free_percent")
    if isinstance(free_percent, (int, float)) and not isinstance(
        free_percent, bool
    ):
        used_percent = 100.0 - float(free_percent)
        return used_percent >= HARD_MEMORY_USED_PERCENT

    used_gb = snapshot.get("used_estimate_gb")
    total_gb = snapshot.get("total_gb")
    if (
        isinstance(used_gb, (int, float))
        and not isinstance(used_gb, bool)
        and isinstance(total_gb, (int, float))
        and not isinstance(total_gb, bool)
        and float(total_gb) > 0
    ):
        return (
            float(used_gb) / float(total_gb) * 100.0
            >= HARD_MEMORY_USED_PERCENT
        )

    return snapshot.get("pressure") == "critical"


def _raise_hard_memory_limit(workload, snapshot):
    used_percent = None
    free_percent = snapshot.get("free_percent") if isinstance(snapshot, dict) else None
    if isinstance(free_percent, (int, float)) and not isinstance(
        free_percent, bool
    ):
        used_percent = max(0.0, min(100.0, 100.0 - float(free_percent)))

    detail = (
        f" ({used_percent:.1f}% geschätzt belegt)"
        if used_percent is not None
        else ""
    )
    raise RuntimeError(
        f"{workload} wurde nicht gestartet: RAM-Hard-Limit von "
        f"{HARD_MEMORY_USED_PERCENT:.0f}% erreicht{detail}. "
        "Erst Speicher freigeben oder einen anderen AI-Runtime entladen."
    )


def model_load_reserve_gb(workload):
    """Return the configured conservative reserve for a model load."""
    return float(MODEL_LOAD_RESERVE_GB.get(str(workload), 0.0))


def projected_memory_hard_limit_reached(snapshot, reserve_gb=0.0):
    """Return whether current RAM plus a conservative load reserve hits the cap."""
    if memory_hard_limit_reached(snapshot):
        return True

    reserve_gb = max(0.0, float(reserve_gb or 0.0))
    if reserve_gb <= 0:
        return False

    used_gb = snapshot.get("used_estimate_gb") if isinstance(snapshot, dict) else None
    total_gb = snapshot.get("total_gb") if isinstance(snapshot, dict) else None
    if (
        isinstance(used_gb, (int, float))
        and not isinstance(used_gb, bool)
        and isinstance(total_gb, (int, float))
        and not isinstance(total_gb, bool)
        and float(total_gb) > 0
    ):
        projected_percent = (
            (float(used_gb) + reserve_gb) / float(total_gb) * 100.0
        )
        return projected_percent >= HARD_MEMORY_USED_PERCENT

    free_percent = snapshot.get("free_percent") if isinstance(snapshot, dict) else None
    if (
        isinstance(free_percent, (int, float))
        and not isinstance(free_percent, bool)
        and isinstance(total_gb, (int, float))
        and not isinstance(total_gb, bool)
        and float(total_gb) > 0
    ):
        reserve_percent = reserve_gb / float(total_gb) * 100.0
        return (100.0 - float(free_percent) + reserve_percent) >= HARD_MEMORY_USED_PERCENT

    return False


def ensure_model_load_allowed(
    workload,
    *,
    snapshot=None,
    reserve_gb=None,
):
    """Reject a new local ML-model load before it can exhaust unified memory."""
    snapshot = snapshot or memory_budget_snapshot()
    if reserve_gb is None:
        reserve_gb = model_load_reserve_gb(workload)
    reserve_gb = max(0.0, float(reserve_gb or 0.0))

    if projected_memory_hard_limit_reached(snapshot, reserve_gb):
        used_gb = snapshot.get("used_estimate_gb")
        total_gb = snapshot.get("total_gb")
        projected = None
        if (
            isinstance(used_gb, (int, float))
            and isinstance(total_gb, (int, float))
            and not isinstance(used_gb, bool)
            and not isinstance(total_gb, bool)
            and float(total_gb) > 0
        ):
            projected = (
                (float(used_gb) + reserve_gb) / float(total_gb) * 100.0
            )

        suffix = (
            f" Prognose mit {reserve_gb:.1f} GB Lade-Reserve: "
            f"{projected:.1f}%."
            if projected is not None
            else (
                f" Konservative Lade-Reserve: {reserve_gb:.1f} GB."
                if reserve_gb
                else ""
            )
        )
        raise RuntimeError(
            f"{workload} wurde nicht geladen: RAM-Sicherheitsgrenze von "
            f"{HARD_MEMORY_USED_PERCENT:.0f}% würde erreicht oder überschritten."
            + suffix
        )

    return snapshot


def _default_chat_loaded():
    """Return whether the launchd-managed shared chat runtime is loaded."""
    try:
        result = subprocess.run(
            [
                "launchctl",
                "print",
                f"gui/{os.getuid()}/{MLX_SERVER_LABEL}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _default_chat_command(action):
    if action not in {"start", "stop"}:
        raise ValueError("Unsupported chat runtime action")
    try:
        result = subprocess.run(
            ["/bin/bash", str(MLX_MANAGER), action],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"mlx {action} fehlgeschlagen") from exc
    if result.returncode != 0:
        message = result.stdout.strip() or f"mlx {action} fehlgeschlagen"
        raise RuntimeError(message[-4000:])


def _state_path(state_dir=STATE_DIR, thread_id=None):
    thread_id = threading.get_ident() if thread_id is None else int(thread_id)
    return state_dir / f"{os.getpid()}-{thread_id}.json"


def _write_lease_state(workload, state, *, state_dir=STATE_DIR):
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = _state_path(state_dir)
        temporary = path.with_name(f".{path.name}.tmp")
        payload = {
            "pid": os.getpid(),
            "thread": threading.get_ident(),
            "workload": workload,
            "state": state,
            "updated_at": time.time(),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        pass


def _clear_lease_state(*, state_dir=STATE_DIR):
    try:
        _state_path(state_dir).unlink(missing_ok=True)
    except OSError:
        pass


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def runtime_state_snapshot(*, state_dir=STATE_DIR):
    """Aggregate active/waiting heavy-runtime leases across native services."""
    entries = []
    try:
        paths = list(state_dir.glob("*.json"))
    except OSError:
        paths = []

    for path in paths:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(item, dict) or not _pid_alive(item.get("pid")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        entries.append(item)

    entries.sort(key=lambda item: float(item.get("updated_at") or 0))
    active = [item for item in entries if item.get("state") == "active"]
    waiting = [item for item in entries if item.get("state") == "waiting"]
    return {
        "active": active[-1] if active else None,
        "waiting": waiting,
        "waiting_count": len(waiting),
        "memory": memory_budget_snapshot(),
    }


def request_json(method, url, payload=None, timeout=10):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1", "localhost", "::1",
    }:
        raise ValueError("Runtime coordinator only accepts local HTTP services")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port,
        timeout=timeout,
    )
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    try:
        connection.request(
            method,
            parsed.path or "/",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        raw = response.read()
        if response.status >= 400:
            raise RuntimeError(
                f"Runtime service returned HTTP {response.status}"
            )
        return json.loads(raw.decode("utf-8"))
    finally:
        connection.close()


@contextmanager
def runtime_lease(
    cancel_event=None,
    *,
    lock_path=LOCK_PATH,
    workload="runtime",
    state_dir=STATE_DIR,
):
    """Hold the cross-service heavy-runtime lease, waiting cancellably."""
    depth = getattr(_LEASE_STATE, "depth", 0)
    if depth:
        _PROCESS_LOCK.acquire()
        _LEASE_STATE.depth = depth + 1
        try:
            yield
        finally:
            _LEASE_STATE.depth -= 1
            _PROCESS_LOCK.release()
        return

    _write_lease_state(workload, "waiting", state_dir=state_dir)
    process_lock_acquired = False
    try:
        while not _PROCESS_LOCK.acquire(timeout=POLL_INTERVAL):
            _check_cancelled(cancel_event)
        process_lock_acquired = True

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            while True:
                _check_cancelled(cancel_event)
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(POLL_INTERVAL)
            _LEASE_STATE.depth = 1
            _write_lease_state(workload, "active", state_dir=state_dir)
            try:
                yield
            finally:
                _LEASE_STATE.depth = 0
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        _clear_lease_state(state_dir=state_dir)
        if process_lock_acquired:
            _PROCESS_LOCK.release()


def _generation_active(health):
    if "active_generation" in health:
        return health.get("active_generation") is True
    return health.get("status") == "busy"


def wait_for_idle(service_url, service_name, cancel_event=None, *, requester=request_json):
    """Wait for real service-reported generation state without cancelling it."""
    while True:
        _check_cancelled(cancel_event)
        try:
            health = requester("GET", service_url + "/health", timeout=10)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ServiceUnavailable(
                f"{service_name}-Service-Zustand konnte nicht geprüft werden"
            ) from exc
        if not _generation_active(health):
            return health
        time.sleep(POLL_INTERVAL)


def release_idle_image_runtime(cancel_event=None, *, requester=request_json):
    """Wait for image work, then unload only a resident idle image runtime."""
    health = wait_for_idle(
        IMAGE_URL, "Image", cancel_event, requester=requester
    )
    _check_cancelled(cancel_event)
    if health.get("loaded"):
        requester("POST", IMAGE_URL + "/unload", {}, timeout=120)
        health = wait_for_idle(
            IMAGE_URL, "Image", cancel_event, requester=requester
        )
        if health.get("loaded"):
            raise RuntimeError("Image-Runtime konnte nicht entladen werden")
    return health


@contextmanager
def video_runtime(
    cancel_event,
    *,
    chat_loaded,
    chat_command,
    restore_error=None,
    requester=request_json,
    lock_path=LOCK_PATH,
):
    """Hand off resources to video while preserving a healthy warm chat runtime."""
    with runtime_lease(
        cancel_event,
        lock_path=lock_path,
        workload="video",
    ):
        image_health = release_idle_image_runtime(
            cancel_event,
            requester=requester,
        )
        _check_cancelled(cancel_event)

        # Measure after releasing idle image weights. This avoids paying a chat
        # cold-start when reclaiming the image runtime already created enough
        # unified-memory headroom for LTX.
        before = memory_budget_snapshot()
        video_reserve_gb = model_load_reserve_gb("video")
        relief_needed = (
            memory_relief_needed(
                before,
                min_headroom_gb=VIDEO_MIN_HEADROOM_GB,
            )
            or projected_memory_hard_limit_reached(
                before,
                video_reserve_gb,
            )
        )
        restore_chat = bool(relief_needed and chat_loaded())
        if restore_chat:
            chat_command("stop")

        admission = memory_budget_snapshot() if restore_chat else before
        preflight = {
            "workload": "video",
            "memory_before": before,
            "memory_admission": admission,
            "memory_relief_needed": relief_needed,
            "hard_limit_reached": projected_memory_hard_limit_reached(
                admission,
                video_reserve_gb,
            ),
            "hard_limit_used_percent": HARD_MEMORY_USED_PERCENT,
            "load_reserve_gb": video_reserve_gb,
            "required_headroom_gb": VIDEO_MIN_HEADROOM_GB,
            "image_released": not bool(image_health.get("loaded")),
            "chat_released": restore_chat,
        }
        try:
            _check_cancelled(cancel_event)
            ensure_model_load_allowed(
                "video",
                snapshot=admission,
                reserve_gb=video_reserve_gb,
            )
            yield preflight
        finally:
            if restore_chat:
                after = memory_budget_snapshot()
                preflight["memory_after"] = after
                restore_unsafe = (
                    memory_relief_needed(after)
                    or memory_hard_limit_reached(after)
                )
                preflight["chat_restore_skipped"] = restore_unsafe
                if restore_unsafe:
                    print(
                        "[runtime-memory] chat restart skipped after video job "
                        "because memory pressure/headroom is still unsafe",
                        flush=True,
                    )
                else:
                    try:
                        chat_command("start")
                    except Exception as exc:
                        if restore_error is None:
                            raise
                        restore_error(exc)


@contextmanager
def image_runtime(
    cancel_event,
    *,
    requester=request_json,
    lock_path=LOCK_PATH,
    chat_loaded=None,
    chat_command=None,
    restore_error=None,
    memory_snapshot=None,
):
    """Run image work with pressure-aware chat-runtime memory handoff."""
    chat_loaded = chat_loaded or _default_chat_loaded
    chat_command = chat_command or _default_chat_command
    memory_snapshot = memory_snapshot or memory_budget_snapshot

    with runtime_lease(
        cancel_event,
        lock_path=lock_path,
        workload="image",
    ):
        wait_for_idle(VIDEO_URL, "Video", cancel_event, requester=requester)
        _check_cancelled(cancel_event)
        before = memory_snapshot()
        image_reserve_gb = model_load_reserve_gb("image")
        relief_needed = (
            memory_relief_needed(before)
            or projected_memory_hard_limit_reached(
                before,
                image_reserve_gb,
            )
        )
        restore_chat = bool(relief_needed and chat_loaded())
        if restore_chat:
            chat_command("stop")

        admission = memory_snapshot() if restore_chat else before
        preflight = {
            "workload": "image",
            "memory_before": before,
            "memory_admission": admission,
            "memory_relief_needed": relief_needed,
            "hard_limit_reached": projected_memory_hard_limit_reached(
                admission,
                image_reserve_gb,
            ),
            "hard_limit_used_percent": HARD_MEMORY_USED_PERCENT,
            "load_reserve_gb": image_reserve_gb,
            "chat_released": restore_chat,
        }
        try:
            _check_cancelled(cancel_event)
            ensure_model_load_allowed(
                "image",
                snapshot=admission,
                reserve_gb=image_reserve_gb,
            )
            yield preflight
        finally:
            if restore_chat:
                after = memory_snapshot()
                preflight["memory_after"] = after
                restore_unsafe = (
                    memory_relief_needed(after)
                    or memory_hard_limit_reached(after)
                )
                preflight["chat_restore_skipped"] = restore_unsafe

                if restore_unsafe:
                    print(
                        "[runtime-memory] chat restart skipped after image job "
                        "because memory pressure/headroom is still unsafe",
                        flush=True,
                    )
                else:
                    try:
                        chat_command("start")
                    except Exception as exc:
                        if restore_error is None:
                            raise
                        restore_error(exc)


def prepare_chat_runtime(*, requester=request_json, lock_path=LOCK_PATH):
    """Release idle image weights before resolving the shared chat runtime.

    This path may run for an already-resident model, so it must not reject
    inference solely because RAM crossed the load-admission threshold. Actual
    chat/VLM process startup is guarded by scripts/runtime-model-guard.py.
    """
    with chat_runtime(requester=requester, lock_path=lock_path):
        return {
            "ok": True,
            "memory": memory_budget_snapshot(),
            "hard_limit_used_percent": HARD_MEMORY_USED_PERCENT,
        }


@contextmanager
def chat_runtime(
    cancel_event=None, *, requester=request_json, lock_path=LOCK_PATH
):
    """Hold the heavy-runtime lease for a chat request."""
    already_coordinated = getattr(_LEASE_STATE, "depth", 0) > 0
    with runtime_lease(
        cancel_event,
        lock_path=lock_path,
        workload="chat",
    ):
        if not already_coordinated:
            try:
                release_idle_image_runtime(cancel_event, requester=requester)
            except ServiceUnavailable:
                # Preserve chat availability when the optional image service
                # is offline. The cross-process lease still excludes any
                # coordinated active generation.
                pass
        _check_cancelled(cancel_event)
        yield
