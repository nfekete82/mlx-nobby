"""Durable admission barrier shared by the agent and native model services.

This coordinates existing queues; it does not own or schedule jobs.
"""
from contextlib import contextmanager
from functools import wraps
import fcntl
import json
import os
from pathlib import Path
import threading
import time

ROOT = Path(os.environ.get("MLX_AI_LIFECYCLE_DIR", Path.home() / ".config/mlx-web/ai-lifecycle"))
_lock = threading.RLock()
_local = threading.local()


class AdmissionClosed(RuntimeError):
    pass


def state():
    try:
        value = json.loads((ROOT / "gate.json").read_text())
        return value if isinstance(value, dict) and type(value.get("blocked")) is bool else {"blocked": True}
    except FileNotFoundError:
        return {"blocked": False}
    except (OSError, ValueError):
        return {"blocked": True, "reason": "Lifecycle-Zustand nicht lesbar"}


def blocked():
    return (ROOT / "shutdown.pending").exists() or state().get("blocked", True)


def check():
    if blocked():
        raise AdmissionClosed("KI-Aufträge sind angehalten; Dienste zuerst erfolgreich neu starten")


@contextmanager
def barrier():
    with _lock:
        if getattr(_local, "depth", 0):
            yield
            return
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (ROOT / "admission.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            _local.depth = 1
            try:
                yield
            finally:
                _local.depth = 0
                fcntl.flock(handle, fcntl.LOCK_UN)


def set_blocked(value, reason=""):
    if value:
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        (ROOT / "shutdown.pending").touch()
    with barrier():
        path = ROOT / "gate.json"
        scratch = path.with_suffix(".tmp")
        scratch.write_text(json.dumps({"blocked": bool(value), "reason": reason,
                                       "updated_at": time.time()}))
        os.replace(scratch, path)
        if not value:
            (ROOT / "shutdown.pending").unlink(missing_ok=True)


def admitted(function):
    """Atomically register an existing job or launch a worker before shutdown."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        with barrier():
            check()
            return function(*args, **kwargs)
    return wrapper


class AIAdmissionGuard:
    """Reject native inference even if its model is already resident."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        inference = path in {"/jobs", "/generate", "/edit", "/upscale", "/embeddings", "/embedding", "/prewarm"} or path.startswith("/v1/")
        if scope.get("type") == "http" and scope.get("method") == "POST" and inference and blocked():
            from starlette.responses import JSONResponse
            await JSONResponse({"detail": "KI-Aufträge sind wegen Shutdown/Neustart angehalten"}, status_code=503)(scope, receive, send)
            return
        await self.app(scope, receive, send)
