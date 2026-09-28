"""Runtime reliability diagnostics and guarded agent self-recovery."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


STATE_DIR = Path(
    os.environ.get(
        "MLX_RUNTIME_COORDINATOR_STATE_DIR",
        f"/tmp/mlx-web-runtime-{os.getuid()}.d",
    )
)
RECOVERY_STATE_FILE = Path.home() / ".config/mlx-web/runtime-recovery.json"
RECOVERY_COOLDOWN_SECONDS = max(
    15.0,
    float(os.environ.get("MLX_RUNTIME_RECOVERY_COOLDOWN", "60")),
)
RECOVERY_MIN_CHAT_AGE_SECONDS = max(
    5.0,
    float(os.environ.get("MLX_RUNTIME_RECOVERY_MIN_CHAT_AGE", "15")),
)
RECOVERY_RESTART_DELAY_SECONDS = max(
    0.25,
    float(os.environ.get("MLX_RUNTIME_RECOVERY_RESTART_DELAY", "0.8")),
)

_RECOVERY_LOCK = threading.Lock()


class RuntimeRecoveryRequest(BaseModel):
    reason: str = Field(default="chat_stalled", min_length=1, max_length=160)
    force: bool = False


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _read_runtime_leases(now: float | None = None) -> dict:
    """Read lightweight coordinator state without invoking memory_pressure."""
    now = float(now if now is not None else time.time())
    entries = []

    try:
        paths = list(STATE_DIR.glob("*.json"))
    except OSError:
        paths = []

    for path in paths:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue

        if not isinstance(item, dict) or not _pid_alive(item.get("pid")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue

        try:
            updated_at = float(item.get("updated_at") or now)
        except (TypeError, ValueError):
            updated_at = now

        item = dict(item)
        item["updated_at"] = updated_at
        item["age_seconds"] = round(max(0.0, now - updated_at), 3)
        entries.append(item)

    entries.sort(key=lambda item: item.get("updated_at", 0.0))
    active = [item for item in entries if item.get("state") == "active"]
    waiting = [item for item in entries if item.get("state") == "waiting"]

    return {
        "active": active[-1] if active else None,
        "waiting": waiting,
        "waiting_count": len(waiting),
        "oldest_wait_seconds": round(
            max((item.get("age_seconds", 0.0) for item in waiting), default=0.0),
            3,
        ),
    }


def _read_recovery_state() -> dict:
    try:
        payload = json.loads(RECOVERY_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_recovery_state(payload: dict) -> None:
    RECOVERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECOVERY_STATE_FILE.with_name(
        f".{RECOVERY_STATE_FILE.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, RECOVERY_STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _recovery_snapshot(now: float | None = None) -> dict:
    now = float(now if now is not None else time.time())
    state = _read_recovery_state()
    try:
        scheduled_at = float(state.get("scheduled_at") or 0.0)
    except (TypeError, ValueError):
        scheduled_at = 0.0

    cooldown_remaining = max(
        0.0,
        RECOVERY_COOLDOWN_SECONDS - (now - scheduled_at),
    ) if scheduled_at else 0.0

    return {
        "last_recovery_at": scheduled_at or None,
        "last_recovery_reason": state.get("reason"),
        "last_recovery_pid": state.get("agent_pid"),
        "cooldown_remaining_seconds": round(cooldown_remaining, 3),
        "cooldown_seconds": RECOVERY_COOLDOWN_SECONDS,
    }


def diagnostics(status_provider: Callable[[], dict] | None = None) -> dict:
    now = time.time()
    leases = _read_runtime_leases(now)
    active = leases.get("active")

    runtime = {}
    if status_provider is not None:
        try:
            value = status_provider()
            if isinstance(value, dict):
                runtime = value
        except Exception as exc:  # diagnostics must never break the agent
            runtime = {"online": False, "error": str(exc)}

    return {
        "status": "ok",
        "agent_pid": os.getpid(),
        "checked_at": now,
        "runtime": {
            "online": runtime.get("online"),
            "model": runtime.get("model"),
            "port": runtime.get("port"),
            "pid": runtime.get("pid"),
            "memory_mb": runtime.get("memory_mb"),
            "error": runtime.get("error"),
        },
        "lease": {
            "active_workload": active.get("workload") if active else None,
            "active_age_seconds": active.get("age_seconds") if active else None,
            "active_pid": active.get("pid") if active else None,
            "active_thread": active.get("thread") if active else None,
            "waiting_count": leases.get("waiting_count", 0),
            "oldest_wait_seconds": leases.get("oldest_wait_seconds", 0.0),
        },
        "recovery": _recovery_snapshot(now),
    }


def _default_restart_scheduler(delay_seconds: float) -> None:
    manager = Path(
        os.environ.get("MLX_MANAGER", str(Path.home() / "bin/mlx"))
    ).expanduser()
    if not manager.exists():
        raise RuntimeError(f"MLX manager not found: {manager}")

    command = (
        f"sleep {float(delay_seconds):.3f}; "
        f"exec {shlex.quote(str(manager))} agent restart"
    )
    subprocess.Popen(
        ["/bin/sh", "-c", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def request_recovery(
    request: RuntimeRecoveryRequest,
    *,
    status_provider: Callable[[], dict] | None = None,
    restart_scheduler: Callable[[float], None] = _default_restart_scheduler,
) -> dict:
    now = time.time()

    with _RECOVERY_LOCK:
        snapshot = diagnostics(status_provider)
        lease = snapshot["lease"]
        active_workload = lease.get("active_workload")
        active_age = float(lease.get("active_age_seconds") or 0.0)
        recovery = snapshot["recovery"]

        if not request.force and active_workload in {"image", "video"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Recovery blocked while {active_workload} runtime is active"
                ),
            )

        if (
            not request.force
            and active_workload == "chat"
            and active_age < RECOVERY_MIN_CHAT_AGE_SECONDS
        ):
            raise HTTPException(
                status_code=409,
                detail="Chat runtime has not been stalled long enough for recovery",
            )

        cooldown_remaining = float(
            recovery.get("cooldown_remaining_seconds") or 0.0
        )
        if not request.force and cooldown_remaining > 0:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Runtime recovery is cooling down for "
                    f"{cooldown_remaining:.1f} seconds"
                ),
            )

        state = {
            "scheduled_at": now,
            "reason": request.reason,
            "agent_pid": os.getpid(),
        }
        _write_recovery_state(state)
        restart_scheduler(RECOVERY_RESTART_DELAY_SECONDS)

        return {
            "ok": True,
            "scheduled": True,
            "reason": request.reason,
            "agent_pid": os.getpid(),
            "restart_delay_seconds": RECOVERY_RESTART_DELAY_SECONDS,
            "cooldown_seconds": RECOVERY_COOLDOWN_SECONDS,
        }


def install_routes(
    app: FastAPI,
    *,
    status_provider: Callable[[], dict] | None = None,
    restart_scheduler: Callable[[float], None] = _default_restart_scheduler,
) -> None:
    paths = {
        getattr(route, "path", None)
        for route in app.router.routes
    }

    if "/api/runtime/reliability" not in paths:
        @app.get("/api/runtime/reliability")
        def runtime_reliability_status():
            return diagnostics(status_provider)

    if "/api/runtime/reliability/recover" not in paths:
        @app.post("/api/runtime/reliability/recover", status_code=202)
        def runtime_reliability_recover(request: RuntimeRecoveryRequest):
            return request_recovery(
                request,
                status_provider=status_provider,
                restart_scheduler=restart_scheduler,
            )


__all__ = [
    "RuntimeRecoveryRequest",
    "diagnostics",
    "install_routes",
    "request_recovery",
]
