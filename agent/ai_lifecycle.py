"""Shutdown adapters for the existing Nobby job registries and launchd trees."""
import json
import os
import signal
import shlex
import subprocess
import threading
import time
import urllib.request

from fastapi import HTTPException

import ai_lifecycle_gate as gate
import managed_process
from agent import media_queue, shorts_jobs, talking_photo, video_edit_routes, run_state

_operation = threading.RLock()
SERVICES = ("server", "router", "embeddings", "speech", "images", "video", "mlxserve")
PORTS = (8000, 8040, 8020, 8050, 8030, 8060, 11234)


def _report(agent, phase, message, current):
    existing = agent._get_system_lifecycle_state()
    agent._set_system_lifecycle_state(action=existing.get("action") or "shutdown-ai",
                                     state="running", phase=phase, message=message,
                                     current=current, total=6)


def _snapshot_service_processes():
    """Ancestry must originate in one of our exact launchd labels."""
    roots = set()
    for name in SERVICES:
        label = "mlx-serve" if name == "mlxserve" else "mlx-" + name
        result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/de.nobby.{label}"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            continue
        for line in result.stdout.splitlines():
            if line.strip().startswith("pid = "):
                roots.add(int(line.strip().split()[-1]))
    table = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True, timeout=5)
    children = [tuple(map(int, line.split())) for line in table.splitlines() if line.strip()]
    # Migration coverage for pre-guard LTX jobs. The exact Agent ancestry AND
    # a canonical Nobby executable path are required; a terminal's LTX is not
    # automatically ours merely because it uses the same model/runtime.
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/de.nobby.mlx-agent"],
                            capture_output=True, text=True, timeout=5)
    agent_roots = {int(line.strip().split()[-1]) for line in result.stdout.splitlines()
                   if line.strip().startswith("pid = ")} if not result.returncode else set()
    descendants = set(agent_roots)
    while True:
        added = {pid for pid, parent in children if parent in descendants} - descendants
        if not added:
            break
        descendants.update(added)
    from pathlib import Path
    known = (str(video_edit_routes.RUNTIME / ".venv/bin/ltx-2-mlx"),
             str(Path(__file__).resolve().parents[1] / "scripts/ltx-talking-photo-a2v.py"))
    for pid in descendants - agent_roots:
        value = managed_process.identity(pid)
        arguments = shlex.split(value)[5:] if value else []
        executable_paths = arguments[:1]
        if arguments and Path(arguments[0]).name.startswith("python"):
            executable_paths += arguments[1:2]
        if any(path in executable_paths for path in known):
            roots.add(pid)
    selected = set(roots)
    while True:
        added = {pid for pid, parent in children if parent in selected} - selected
        if not added:
            break
        selected.update(added)
    return [{"pid": pid, "identity": value} for pid in selected
            if (value := managed_process.identity(pid))]


def _same_process(item):
    return managed_process.identity(item["pid"]) == item["identity"]


def _finish_service_processes(records):
    # Individual identities remain verifiable even after launchd/parent exit.
    for sig, timeout in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        live = [item for item in records if _same_process(item)]
        for item in live:
            try:
                os.kill(item["pid"], sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + timeout
        while any(_same_process(item) for item in live) and time.monotonic() < deadline:
            time.sleep(0.1)
    remaining = [str(item["pid"]) for item in records if _same_process(item)]
    if remaining:
        raise RuntimeError("KI-Prozesse laufen weiter: " + ", ".join(remaining))


def quiesce(agent):
    with _operation:
        gate.set_blocked(True, "shutdown")
        (gate.ROOT / "shutdown-verified.json").unlink(missing_ok=True)
        _report(agent, "blocking", "Neue Aufträge werden angehalten", 0)
        records = _snapshot_service_processes()
        path = gate.ROOT / "service-processes.json"
        # Preserve identities from a previous failed attempt or Agent restart.
        if path.exists():
            records += json.loads(path.read_text())
        scratch = path.with_suffix(".tmp")
        scratch.write_text(json.dumps(records))
        os.replace(scratch, path)
        _report(agent, "cancelling", "Laufende Aufträge werden abgebrochen", 1)
        video_edit_routes.cancel_all()
        run_state.cancel_all()
        with media_queue._jobs_lock:
            media_queue._ensure_loaded_locked()
            jobs = [(j["kind"], j["id"]) for j in media_queue._jobs.values()
                    if j["status"] not in media_queue.TERMINAL]
        for kind, job_id in jobs:
            try:
                media_queue.cancel(kind, job_id, reason="lifecycle")
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        with shorts_jobs._jobs_lock:
            shorts = [j["id"] for j in shorts_jobs._load_jobs().values()
                      if j["status"] not in shorts_jobs.TERMINAL_STATUSES]
        for job_id in shorts:
            try:
                shorts_jobs.cancel_short_job(job_id)
            except ValueError:
                if shorts_jobs.get_short_job(job_id).get("status") not in shorts_jobs.TERMINAL_STATUSES:
                    raise
        with talking_photo._jobs_lock:
            for path in talking_photo.JOBS.glob("*.json"):
                job = json.loads(path.read_text())
                if job.get("status") in talking_photo.ACTIVE_STATUSES:
                    talking_photo.cancel_job(job["id"])
        with agent.BATCH_LOCK:
            batch = agent.load_batch_jobs()
            for job in batch.values():
                if job.get("status") in {"queued", "running", "paused", "interrupted"}:
                    job.update(status="cancelled", finished_at=time.time())
            agent.save_batch_jobs(batch)
        # Existing cancellation loops get a bounded cooperative grace period.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with video_edit_routes._jlock:
                active = any(j["status"] in video_edit_routes.ACTIVE
                             for j in video_edit_routes._jobs.values())
            if not active:
                break
            time.sleep(0.1)
        _report(agent, "terminating", "KI-Unterprozesse werden beendet", 2)
        managed_process.stop_all()
        _report(agent, "releasing", "Modell-Dienste und Ressourcen werden freigegeben", 3)
        return {"quiesced": True, "blocked": True}


def verify_stopped(agent):
    with _operation:
        gate.set_blocked(True, "verify shutdown")
        _report(agent, "verifying", "Gestoppte Dienste werden überprüft", 4)
        path = gate.ROOT / "service-processes.json"
        if path.exists():
            _finish_service_processes(json.loads(path.read_text()))
        managed_process.stop_all()
        for name, port in zip(SERVICES, PORTS):
            label = "mlx-serve" if name == "mlxserve" else "mlx-" + name
            result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/de.nobby.{label}"],
                                    capture_output=True, timeout=5)
            if not result.returncode:
                raise RuntimeError(f"LaunchAgent {name} ist weiterhin geladen")
            result = subprocess.run(["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
                                    capture_output=True, timeout=5)
            if result.stdout.strip():
                raise RuntimeError(f"Port {port} ist weiterhin belegt; kein fremder Prozess wird beendet")
        deadline = time.monotonic() + 20
        pending = []
        while True:
            with video_edit_routes._jlock:
                active = any(j["status"] in video_edit_routes.ACTIVE
                             for j in video_edit_routes._jobs.values())
            pending = [thread.name for thread in threading.enumerate()
                       if thread is not threading.current_thread() and thread.is_alive()
                       and thread.name.startswith(("nobby-ltx-edit-", "talking-photo-", "mlx-short-",
                                                   "file-analysis-", "batch-", "document-index-", "mlx-chat-stream"))]
            if not active and not pending and not video_edit_routes._generation_lock.locked() and not run_state.active_agent_run_count():
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("KI-Worker geben Ressourcen nicht frei: " + ", ".join(pending or ["Runtime-Lock/Agent-Auftrag"]))
            time.sleep(0.1)
        # Native servers are now confirmed dead, so their queued proxies can
        # be made terminal even if a network poll was interrupted by bootout.
        with video_edit_routes._jlock:
            for job in video_edit_routes._jobs.values():
                if job.get("cleanup_failed"):
                    (video_edit_routes.OUTPUT / f".{job['id']}.partial.mp4").unlink(missing_ok=True)
                    job["cleanup_failed"] = False
                    video_edit_routes._write(job)
        with media_queue._jobs_lock:
            for job in media_queue._jobs.values():
                if job["status"] not in media_queue.TERMINAL:
                    media_queue._update(job["id"], status="cancelled", phase="cancelled",
                                        finished_at=time.time(), error=None)
        with talking_photo._jobs_lock:
            for job_path in talking_photo.JOBS.glob("*.json"):
                job = json.loads(job_path.read_text())
                if job.get("status") in talking_photo.ACTIVE_STATUSES:
                    talking_photo._update_job(job["id"], status="cancelled", phase="cancelled",
                                              finished_at=time.time())
        path.unlink(missing_ok=True)
        (gate.ROOT / "shutdown-verified.json").write_text(json.dumps({"verified_at": time.time()}))
        _report(agent, "stopped", "KI-Prozesse nachweislich gestoppt", 6)
        return {"verified": True, "blocked": True}


def resume(agent):
    """Release admission only after API probes, including model discovery."""
    if not (gate.ROOT / "shutdown-verified.json").is_file():
        raise RuntimeError("Vollständiger Shutdown wurde noch nicht verifiziert")
    _report(agent, "readiness", "Dienste und APIs werden geprüft", 5)
    for name, port in zip(SERVICES, PORTS):
        endpoint = "/v1/models" if name in {"server", "mlxserve", "router"} else "/health"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=5) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or payload.get("ok") is False or payload.get("status") in {"error", "failed"}:
            raise RuntimeError(f"{name}: API meldet keine Betriebsbereitschaft")
        if endpoint == "/health" and (payload.get("status") not in {"ready", "ok"}
                                      or payload.get("active_generation") or payload.get("active_job_id")):
            raise RuntimeError(f"{name}: Runtime ist noch beschäftigt oder nicht bereit")
        if endpoint == "/v1/models" and not payload.get("data"):
            raise RuntimeError(f"{name}: keine Modelle verfügbar")
    gate.set_blocked(False, "APIs verified")
    return {"ready": True, "blocked": False}


def install_routes(app, agent):
    def make_endpoint(function):
        def endpoint(payload: dict | None = None):
            try:
                with _operation:
                    action = (payload or {}).get("action")
                    if function is quiesce and action in {"shutdown-ai", "reboot", "restart-all"}:
                        agent._set_system_lifecycle_state(state="running", action=action, phase="blocking",
                                                          message="Neue Aufträge werden angehalten")
                    return function(agent)
            except Exception as exc:
                gate.set_blocked(True, str(exc))
                agent._set_system_lifecycle_state(state="failed", phase="failed", error=str(exc), message=str(exc))
                raise HTTPException(503, str(exc)) from exc
        return endpoint
    for operation, function in (("quiesce", quiesce), ("verify-stopped", verify_stopped), ("resume", resume)):
        app.post("/api/system/ai/" + operation)(make_endpoint(function))
