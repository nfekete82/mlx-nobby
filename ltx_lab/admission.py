"""Cross-process request admission. Persistent recovery fence survives owner death.

This module has no MLX/server imports and does not activate a production gate.
"""
from __future__ import annotations

import contextvars
import fcntl
import hashlib
import hmac
import json
import math
import os
import secrets
from contextlib import contextmanager
from pathlib import Path

PROTOCOL = 1
BUILD = hashlib.sha256(b"".join((Path(__file__).parent / p).read_bytes()
                              for p in ("admission.py", "guarded_serve.py", "queue_admission.py"))).hexdigest()
CURRENT = contextvars.ContextVar("ltx_admission_ticket", default=None)


class AdmissionDenied(RuntimeError):
    pass


def default_root():
    return Path(os.environ.get("MLX_LAB_ADMISSION_DIR", f"/tmp/mlx-web-benchmark-{os.getuid()}"))


class Gate:
    def __init__(self, root=None):
        self.root = Path(root or default_root()).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise AdmissionDenied("Admission directory must be private and owned by this user")

    @contextmanager
    def mutex(self):
        with (self.root / "control.lock").open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def state(self):
        path = self.root / "state.json"
        return json.loads(path.read_text()) if path.exists() else {"status": "idle"}

    def save(self, data):
        tmp = self.root / "state.tmp"
        with tmp.open("w") as f:
            os.chmod(tmp, 0o600)
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.root / "state.json")
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def identity(self):
        path = self.root / "gate.lock"
        with path.open("a+"):
            stat = path.stat()
        return hashlib.sha256(f"{self.root}:{stat.st_dev}:{stat.st_ino}".encode()).hexdigest()

    def ticket(self):
        with self.mutex():
            if self.state()["status"] != "idle":
                raise AdmissionDenied("Exclusive benchmark or recovery pending; retry after recovery")
            f = (self.root / "gate.lock").open("a+")
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BaseException:
                f.close()
                raise AdmissionDenied("Exclusive benchmark admission busy") from None
        return Ticket(self, f)

    def startup_ticket(self, role):
        """Startup may load weights before the first HTTP request: fence it too."""
        with self.mutex():
            state = self.state()
            if state["status"] != "idle":
                if role != "musetalk" or not self.owner_alive():
                    raise AdmissionDenied("Model-loading startup blocked by benchmark/recovery")
                path = Path(state["journal"])
                service_path = path.parent / "service-session.json"
                service = json.loads(service_path.read_text())
                session = json.loads(path.read_text())
                model_path = path.parent / "model-session.json"
                model = json.loads(model_path.read_text()) if model_path.exists() else {}
                if (service.get("approved_restart") is not True
                        or "musetalk" not in service.get("pending_services", [])
                        or session.get("child_may_be_alive") or model.get("child_may_be_alive")):
                    raise AdmissionDenied("Service restart not approved or lab child exit unconfirmed")
                if not self.safe_restore_memory():
                    raise AdmissionDenied("Insufficient safe memory for service restart")
                # A single restart attempt; a failed startup requires renewed approval.
                from .exclusive import private_json
                service["approved_restart"] = False
                private_json(service_path, service)
                return Ticket(self, None)
        return self.ticket()

    @staticmethod
    def safe_restore_memory():
        from .telemetry import system_snapshot
        snap = system_snapshot()
        available = snap.get("available_estimate_bytes")
        return (snap.get("memory_pressure_level") == 1 and snap.get("swap_used_bytes") is not None
                and isinstance(available, (int, float)) and not isinstance(available, bool)
                and math.isfinite(available) and available >= 20 * 1024**3)

    def privileged(self, secret, role, method, path):
        vlm_restore = role in {"chat", "router"} and path in {"/unload", "/chat/completions"}
        muse_restore = role == "musetalk" and path == "/warmup"
        if (method != "POST" or not (vlm_restore or muse_restore)
                or not isinstance(secret, str) or len(secret) != 64):
            return False
        try:
            state = self.state()
        except (OSError, ValueError):
            return False
        if muse_restore:
            try:
                service = json.loads((Path(state["journal"]).parent / "service-session.json").read_text())
                if (service.get("approved_restore_warmup") is not True
                        or "musetalk" not in service.get("pending_services", [])):
                    return False
                if not self.safe_restore_memory():
                    return False
            except (OSError, ValueError, KeyError):
                return False
        return (state["status"] in {"exclusive", "recovery_required"}
                and isinstance(secret, str) and len(secret) == 64
                and hmac.compare_digest(state.get("secret_hash", ""), hashlib.sha256(secret.encode()).hexdigest())
                and self.owner_alive())

    def owner_alive(self):
        # OS lock, not PID/mtime: PID reuse and owner crashes must not grant privileges.
        with (self.root / "gate.lock").open("a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    @contextmanager
    def exclusive(self, journal, recovery=None):
        """Never waits for/interrupts admitted requests. Never clears an unresolved fence."""
        with self.mutex():
            state = self.state()
            if recovery:
                if (state.get("session") != recovery["session"] or not hmac.compare_digest(
                        state.get("secret_hash", ""), hashlib.sha256(recovery["secret"].encode()).hexdigest())):
                    raise AdmissionDenied("Recovery credentials do not match the admission fence")
            elif state["status"] != "idle":
                raise AdmissionDenied("Unresolved admission session; explicit recovery required")
            f = (self.root / "gate.lock").open("a+")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                f.close()
                raise AdmissionDenied("Existing requests/jobs still admitted; nothing interrupted") from None
            credentials = recovery or {"session": secrets.token_hex(16), "secret": secrets.token_hex(32)}
            try:
                self.save({"status": "exclusive", "session": credentials["session"],
                           "secret_hash": hashlib.sha256(credentials["secret"].encode()).hexdigest(),
                           "journal": str(journal), "owner_pid": os.getpid()})
            except BaseException:
                f.close()
                raise
        completed = False
        def complete():
            nonlocal completed
            completed = True
        try:
            yield credentials, complete
        finally:
            with self.mutex():
                try:
                    if completed:
                        self.save({"status": "idle"})
                    else:
                        state = self.state()
                        state["status"] = "recovery_required"
                        self.save(state)
                finally:
                    f.close()


class Ticket:
    def __init__(self, gate, file):
        self.gate, self.file = gate, file
    def close(self):
        if self.file is not None:
            self.file.close()


class AdmissionMiddleware:
    """Conservative write/WS admission; read-only status stays available.

    Long-running GET inference must be declared explicitly by each server adapter.
    """
    def __init__(self, app, *, role, gate=None, offline=False, tracking=False, hub_cache=None, refresh=None,
                 model_resolutions=None):
        self.app, self.role, self.gate = app, role, gate or Gate()
        self.offline = offline
        self.tracking = tracking
        self.hub_cache = hub_cache
        self.refresh = refresh
        self.model_resolutions = model_resolutions if model_resolutions is not None else {}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            ticket = None
            async def startup_receive():
                nonlocal ticket
                message = await receive()
                if message["type"] == "lifespan.startup":
                    ticket = self.gate.startup_ticket(self.role)
                return message
            async def startup_send(message):
                nonlocal ticket
                if message["type"] in {"lifespan.startup.complete", "lifespan.startup.failed"} and ticket:
                    ticket.close()
                    ticket = None
                await send(message)
            try:
                return await self.app(scope, startup_receive, startup_send)
            finally:
                if ticket:
                    ticket.close()
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path, method = scope.get("path", ""), scope.get("method", "WS")
        if path == "/lab/admission" and method == "GET":
            observed = (self.refresh() or {}) if self.refresh else {}
            body = json.dumps({"protocol": PROTOCOL, "role": self.role, "pid": os.getpid(),
                               "gate": self.gate.identity(), "offline": self.offline,
                               "status": self.gate.state()["status"], "thread_tracking": self.tracking,
                               "implementation": BUILD, "hub_cache": self.hub_cache,
                               "model_resolutions": self.model_resolutions,
                               "job_blockers": observed.get("job_blockers", [])}).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        # GET may run inference in some adapters; allow only documented read-only routes.
        safe = method in {"HEAD", "OPTIONS"} or (method == "GET" and
            (path in {"/health", "/metrics", "/v1/metrics", "/props", "/openapi.json", "/v1/settings",
                      "/models", "/v1/models", "/jobs", "/api/talking-photo/jobs", "/"}
             or path.startswith(("/jobs/", "/api/talking-photo/jobs/"))))
        headers = dict(scope.get("headers", []))
        secret = headers.get(b"x-ltx-lab-session", b"").decode("ascii", errors="ignore")
        if safe or self.gate.privileged(secret, self.role, method, path):
            return await self.app(scope, receive, send)
        try:
            ticket = self.gate.ticket()
        except (AdmissionDenied, OSError, ValueError, KeyError):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await send({"type": "http.response.start", "status": 423,
                            "headers": [(b"content-type", b"application/json"), (b"retry-after", b"30")]})
                await send({"type": "http.response.body", "body": b'{"error":"benchmark_exclusive_or_recovery_pending"}'})
            return
        token = CURRENT.set(ticket)
        try:
            return await self.app(scope, receive, send)
        finally:
            CURRENT.reset(token)
            ticket.close()
