"""Admission proof and recovery fence around the complete benchmark/restore session."""
from __future__ import annotations

import json
import os
import urllib.error
from contextlib import contextmanager
from pathlib import Path

from .admission import AdmissionDenied, Gate, PROTOCOL, BUILD
from .services import api
from .telemetry import command, preflight

PORTS = {8000: "chat", 8010: "agent", 8020: "embedding", 8030: "image", 8040: "router",
         8050: "speech", 8060: "video", 8070: "musetalk", 11234: "mlxserve"}


def private_json(path, data):
    path = Path(path)
    # Make the temporary inode private before writing the recovery credential.
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", closefd=False) as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    temporary.replace(path)


def verify_services(gate, read=api, inspect=command):
    evidence = {}
    for port, role in PORTS.items():
        try:
            proof = read("GET", f"http://127.0.0.1:{port}/lab/admission")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError):
                evidence[role] = {"listener": "absent"}
                continue
            raise AdmissionDenied(f"Admission proof unavailable for {role}: {exc}") from exc
        except Exception as exc:
            raise AdmissionDenied(f"Admission proof missing for {role}: {exc}") from exc
        listeners = inspect(["/usr/sbin/lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN", "-Fp"])
        pids = {int(line[1:]) for line in listeners.splitlines() if line.startswith("p") and line[1:].isdigit()}
        if (proof.get("protocol") != PROTOCOL or proof.get("gate") != gate.identity()
                or proof.get("implementation") != BUILD
                or proof.get("job_blockers") != []
                or proof.get("role") != role or proof.get("thread_tracking") is not True
                or pids != {proof.get("pid")}
                or (role in {"chat", "router", "musetalk"} and proof.get("offline") is not True)):
            raise AdmissionDenied(f"Unverified admission/offline deployment: {role}")
        evidence[role] = proof
    return evidence


@contextmanager
def benchmark_access(path, recovery=False):
    path = Path(path)
    gate = Gate()
    saved = json.loads(path.read_text()) if recovery else None
    credentials = saved["admission"] if saved else None
    # Check installed listeners before creating a durable fence. No service controls.
    verify_services(gate)
    with gate.exclusive(path, recovery=credentials) as (credentials, complete):
        data = saved or {"admission": credentials, "status": "admission_prepared",
                         "child_may_be_alive": False, "child_pid": None}
        private_json(path, data)
        failed = False
        try:
            data["proof"] = verify_services(gate)
            private_json(path, data)
            yield data
        except BaseException:
            failed = True
            raise
        finally:
            # A crash before this finally leaves the EX/recovery fence on disk.
            model_path = path.parent / "model-session.json"
            model = json.loads(model_path.read_text()) if model_path.exists() else {}
            service_path = path.parent / "service-session.json"
            service = json.loads(service_path.read_text()) if service_path.exists() else {}
            pending = (data.get("child_may_be_alive") or model.get("pending_restore")
                       or model.get("child_may_be_alive") or model.get("status") == "restore_pending"
                       or service.get("pending_services") or service.get("status") == "restore_pending")
            if recovery and failed:
                pending = True
            if not pending and not model and data.get("child_pid"):
                # Unmanaged runs have no model restore health check to rely on.
                report = preflight()
                data["final_health"] = report
                pending = not report["allowed"]
            data["status"] = "recovery_required" if pending else "restored"
            private_json(path, data)
            if not pending:
                complete()
            elif not failed:
                raise AdmissionDenied(f"Restore/recovery incomplete; admission remains fenced: {path}")


def model_transport(credentials):
    def request(method, url, payload=None, timeout=5):
        return api(method, url, payload, timeout=timeout,
                   session_secret=credentials["secret"] if method == "POST" else None)
    return request
