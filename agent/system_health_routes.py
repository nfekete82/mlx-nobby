"""System Health & Self-Healing v1 for local MLX Nobby services."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException

from agent import media_queue


PROJECT_DIR = Path(__file__).resolve().parents[1]
STUCK_SECONDS = max(
    30,
    int(os.environ.get("MLX_SYSTEM_HEALTH_STUCK_SECONDS", "90")),
)

SERVICE_SPECS = (
    {
        "id": "runtime",
        "name": "LLM Runtime",
        "port": 8000,
        "label": "de.nobby.mlx-server",
        "paths": ("/health",),
    },
    {
        "id": "agent",
        "name": "Agent",
        "port": 8010,
        "label": "de.nobby.mlx-agent",
        "paths": (),
        "self": True,
    },
    {
        "id": "embeddings",
        "name": "Embeddings",
        "port": 8020,
        "label": "de.nobby.mlx-embeddings",
        "paths": ("/health",),
    },
    {
        "id": "images",
        "name": "Images",
        "port": 8030,
        "label": "de.nobby.mlx-images",
        "paths": ("/health",),
    },
    {
        "id": "router",
        "name": "Router / Vision",
        "port": 8040,
        "label": "de.nobby.mlx-router",
        "paths": ("/health",),
    },
    {
        "id": "speech",
        "name": "Speech",
        "port": 8050,
        "label": "de.nobby.mlx-speech",
        "paths": ("/health",),
    },
    {
        "id": "video",
        "name": "Video",
        "port": 8060,
        "label": "de.nobby.mlx-video",
        "paths": ("/health",),
    },
    {
        "id": "web",
        "name": "Web UI",
        "port": 8090,
        "label": None,
        "paths": ("/api/health",),
        "restart": "docker",
    },
    {
        "id": "mlxserve",
        "name": "MLX Serve",
        "port": 11234,
        "label": "de.nobby.mlx-serve",
        "paths": ("/v1/models", "/health"),
    },
)
SERVICE_BY_ID = {item["id"]: item for item in SERVICE_SPECS}

_progress_lock = threading.Lock()
_progress_observations: dict[str, dict] = {}


def _run(command, timeout=5):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_elapsed(value: str | None) -> int | None:
    """Parse BSD ps elapsed time such as 2-03:04:05 or 03:04."""
    value = str(value or "").strip()
    if not value:
        return None

    days = 0
    if "-" in value:
        day_value, value = value.split("-", 1)
        try:
            days = int(day_value)
        except ValueError:
            return None

    try:
        parts = [int(item) for item in value.split(":")]
    except ValueError:
        return None

    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        return None

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _launchd_snapshot(label: str | None) -> dict:
    if not label:
        return {
            "loaded": None,
            "state": None,
            "pid": None,
            "stderr_path": None,
        }

    domain = f"gui/{os.getuid()}/{label}"
    try:
        result = _run(["launchctl", "print", domain], timeout=4)
    except (OSError, subprocess.SubprocessError):
        return {
            "loaded": False,
            "state": None,
            "pid": None,
            "stderr_path": None,
        }

    if result.returncode != 0:
        return {
            "loaded": False,
            "state": None,
            "pid": None,
            "stderr_path": None,
        }

    text = result.stdout
    pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", text)
    state_match = re.search(r"(?m)^\s*state\s*=\s*([^\n]+)$", text)
    stderr_match = re.search(r"(?m)^\s*stderr path\s*=\s*([^\n]+)$", text)

    return {
        "loaded": True,
        "state": state_match.group(1).strip() if state_match else None,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "stderr_path": stderr_match.group(1).strip() if stderr_match else None,
    }


def _listener_pid(port: int) -> int | None:
    try:
        result = _run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"],
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    for line in result.stdout.splitlines():
        try:
            value = int(line.strip())
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _process_snapshot(pid: int | None) -> dict:
    if not pid:
        return {"rss_bytes": None, "uptime_seconds": None}
    try:
        result = _run(
            ["ps", "-p", str(pid), "-o", "rss=", "-o", "etime="],
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return {"rss_bytes": None, "uptime_seconds": None}

    line = result.stdout.strip()
    if result.returncode != 0 or not line:
        return {"rss_bytes": None, "uptime_seconds": None}

    parts = line.split(None, 1)
    try:
        rss_bytes = int(parts[0]) * 1024
    except (ValueError, IndexError):
        rss_bytes = None

    elapsed = parts[1].strip() if len(parts) > 1 else ""
    return {
        "rss_bytes": rss_bytes,
        "uptime_seconds": _parse_elapsed(elapsed),
    }


def _last_error(path_value: str | None) -> str | None:
    if not path_value:
        return None
    try:
        path = Path(path_value).expanduser().resolve()
        if not path.is_file():
            return None
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > 65536:
                handle.seek(size - 65536)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if re.search(r"error|traceback|exception|fatal|killed|out of memory|oom", line, re.I):
            return line[-500:]
    return None


def _json_probe(port: int, paths: tuple[str, ...]) -> tuple[bool, dict | None, str | None, int | None]:
    if not paths:
        return True, {"ok": True}, None, 0

    last_error = None
    for path in paths:
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}",
                timeout=2.5,
            ) as response:
                raw = response.read()
                latency_ms = int((time.perf_counter() - started) * 1000)
                if response.status < 200 or response.status >= 300:
                    last_error = f"HTTP {response.status}"
                    continue
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                return True, payload if isinstance(payload, dict) else {}, None, latency_ms
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = str(getattr(exc, "reason", exc))[-300:]
    return False, None, last_error or "unavailable", None


def _model_from_health(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in (
        "running_model",
        "runtime_model",
        "model",
        "default_model",
        "tts_model",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    data = payload.get("data")
    if isinstance(data, list):
        loaded = [
            str(item.get("id"))
            for item in data
            if isinstance(item, dict) and item.get("loaded") is True and item.get("id")
        ]
        if loaded:
            return ", ".join(loaded[:3])
    return None


def _active_job_from_health(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("active_job_id") or payload.get("job_id")
    return str(value) if value else None


def _service_snapshot(spec: dict) -> dict:
    launchd = _launchd_snapshot(spec.get("label"))
    pid = launchd.get("pid") or _listener_pid(int(spec["port"]))
    process = _process_snapshot(pid)

    if spec.get("self"):
        probe_ok = True
        payload = {"ok": True}
        probe_error = None
        latency_ms = 0
        pid = os.getpid()
        process = _process_snapshot(pid)
    else:
        probe_ok, payload, probe_error, latency_ms = _json_probe(
            int(spec["port"]), tuple(spec.get("paths") or ())
        )

    if probe_ok:
        status = "healthy"
    elif launchd.get("loaded") is True or pid:
        status = "degraded"
    else:
        status = "down"

    return {
        "id": spec["id"],
        "name": spec["name"],
        "port": int(spec["port"]),
        "status": status,
        "probe_ok": probe_ok,
        "latency_ms": latency_ms,
        "pid": pid,
        "uptime_seconds": process.get("uptime_seconds"),
        "rss_bytes": process.get("rss_bytes"),
        "launchd_loaded": launchd.get("loaded"),
        "launchd_state": launchd.get("state"),
        "current_model": _model_from_health(payload),
        "active_job_id": _active_job_from_health(payload),
        "detail": probe_error,
        "last_error": _last_error(launchd.get("stderr_path")),
        "restartable": True,
    }


def _progress_signature(job: dict) -> tuple:
    return (
        job.get("status"),
        job.get("phase"),
        job.get("progress"),
        job.get("current_step"),
        job.get("total_steps"),
        job.get("current_scene"),
    )


def _observe_stuck_jobs(queue_snapshot: dict, now: float | None = None) -> list[dict]:
    now = float(now if now is not None else time.time())
    jobs = [
        job
        for job in queue_snapshot.get("jobs", [])
        if isinstance(job, dict) and job.get("queue_status") == "running"
    ]
    active_ids = {str(job.get("id")) for job in jobs if job.get("id")}
    stuck = []

    with _progress_lock:
        for key in list(_progress_observations):
            if key not in active_ids:
                _progress_observations.pop(key, None)

        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id:
                continue
            signature = _progress_signature(job)
            observation = _progress_observations.get(job_id)
            if observation is None or observation.get("signature") != signature:
                observation = {"signature": signature, "last_change": now}
                _progress_observations[job_id] = observation

            idle_seconds = max(0, int(now - float(observation["last_change"])))
            if idle_seconds >= STUCK_SECONDS:
                stuck.append({
                    "id": job_id,
                    "kind": job.get("kind"),
                    "title": job.get("title"),
                    "status": job.get("status"),
                    "phase": job.get("phase"),
                    "progress": job.get("progress"),
                    "current_step": job.get("current_step"),
                    "total_steps": job.get("total_steps"),
                    "idle_seconds": idle_seconds,
                })

    return stuck


def build_health_snapshot() -> dict:
    services = [_service_snapshot(spec) for spec in SERVICE_SPECS]
    queue_snapshot = media_queue.snapshot(limit=40)
    stuck_jobs = _observe_stuck_jobs(queue_snapshot)
    healthy = sum(service["status"] == "healthy" for service in services)
    rss_total = sum(int(service.get("rss_bytes") or 0) for service in services)

    return {
        "ok": healthy == len(services) and not stuck_jobs,
        "version": 1,
        "checked_at": time.time(),
        "stuck_threshold_seconds": STUCK_SECONDS,
        "summary": {
            "healthy": healthy,
            "total": len(services),
            "degraded": sum(service["status"] == "degraded" for service in services),
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


def _restart_launchd(spec: dict) -> dict:
    label = spec.get("label")
    if not label:
        raise RuntimeError("service is not managed by launchd")
    domain = f"gui/{os.getuid()}/{label}"

    if spec.get("id") == "agent":
        command = (
            "sleep 0.35; exec launchctl kickstart -k " +
            shlex.quote(domain)
        )
        subprocess.Popen(
            ["/bin/sh", "-c", command],
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"scheduled": True}

    result = _run(["launchctl", "kickstart", "-k", domain], timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "launchctl failed")[-1000:])
    return {"scheduled": False}


def restart_service(service_id: str) -> dict:
    spec = SERVICE_BY_ID.get(str(service_id))
    if spec is None:
        raise HTTPException(404, "Unknown service")

    try:
        if spec.get("restart") == "docker":
            result = _run(
                ["docker", "compose", "restart", "mlx-web"],
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "docker restart failed")[-1000:])
            restart = {"scheduled": False}
        else:
            restart = _restart_launchd(spec)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise HTTPException(500, str(exc)) from exc

    return {
        "ok": True,
        "service": spec["id"],
        "name": spec["name"],
        **restart,
    }


def _retry_stuck_media_job(job: dict) -> dict | None:
    job_id = str(job.get("id") or "")
    kind = str(job.get("kind") or "")
    if kind not in {"image", "video"} or not job_id:
        return None

    with media_queue._jobs_lock:  # noqa: SLF001 - same-package recovery path
        media_queue._ensure_loaded_locked()  # noqa: SLF001
        raw = deepcopy(media_queue._jobs.get(job_id))  # noqa: SLF001

    if not raw or not isinstance(raw.get("request"), dict):
        return None

    request_payload = deepcopy(raw["request"])
    try:
        media_queue.cancel(kind, job_id)
    except HTTPException:
        return None

    new_job = media_queue.enqueue(kind, request_payload)
    with _progress_lock:
        _progress_observations.pop(job_id, None)

    return {
        "old_id": job_id,
        "kind": kind,
        "job": new_job,
    }


def self_heal() -> dict:
    before = build_health_snapshot()
    restarted = []
    failed_restarts = []

    for service in before["services"]:
        if service["status"] == "healthy":
            continue
        # The endpoint itself proves the Agent is alive; never restart the
        # current request handler as part of the automatic batch action.
        if service["id"] in {"agent", "web"}:
            continue
        try:
            restarted.append(restart_service(service["id"]))
        except HTTPException as exc:
            failed_restarts.append({
                "service": service["id"],
                "error": str(exc.detail),
            })

    retries = []
    for job in before.get("stuck_jobs", []):
        retried = _retry_stuck_media_job(job)
        if retried is not None:
            retries.append(retried)

    return {
        "ok": not failed_restarts,
        "restarted_services": restarted,
        "failed_restarts": failed_restarts,
        "job_retries": retries,
        "checked_at": time.time(),
    }


def install_routes(app: FastAPI) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/system/health-v1" not in paths:
        @app.get("/api/system/health-v1")
        def system_health_v1():
            return build_health_snapshot()

    if "/api/system/services/{service_id}/restart" not in paths:
        @app.post("/api/system/services/{service_id}/restart")
        def system_service_restart(service_id: str):
            return restart_service(service_id)

    if "/api/system/self-heal" not in paths:
        @app.post("/api/system/self-heal")
        def system_self_heal():
            return self_heal()


__all__ = [
    "SERVICE_SPECS",
    "STUCK_SECONDS",
    "_model_from_health",
    "_observe_stuck_jobs",
    "_parse_elapsed",
    "build_health_snapshot",
    "install_routes",
    "restart_service",
    "self_heal",
]
