"""Residency/activity evidence and constrained opt-in HTTP transport. No MLX imports."""
from __future__ import annotations

import json
import math
import os
import shlex
import urllib.request

VLM = {8000: "chat", 8040: "router"}
URLS = {name: f"http://127.0.0.1:{port}" for port, name in VLM.items()}


def api(method, url, payload=None, timeout=5, session_secret=None):
    """Only existing management/read and OpenAI restore routes on fixed loopback ports."""
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    allowed = {"GET": {"/health", "/metrics", "/props", "/v1/settings", "/openapi.json", "/lab/admission"},
               "POST": {"/unload", "/chat/completions"}}
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port not in {8000, 8010, 8020, 8040, 8030, 8050, 8060, 8070, 11234}
            or parsed.path not in allowed.get(method, set()) or parsed.query
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("Unexpected lab service endpoint")
    if method == "POST" and parsed.port not in VLM:
        raise ValueError("Mutations are restricted to explicitly approved VLM services")
    request = urllib.request.Request(url, method=method,
                                    data=json.dumps(payload).encode() if payload is not None else None,
                                    headers={"Accept": "application/json", "Content-Type": "application/json"})
    if session_secret:
        if method != "POST" or len(session_secret) != 64:
            raise ValueError("Invalid session credential use")
        request.add_header("X-LTX-Lab-Session", session_secret)
    # Never follow redirects for management operations, even to another local endpoint.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Oversized management response")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected management JSON object")
        return value


def zero(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == 0


def classify_vlm(health, metrics):
    """An explicit empty model map plus idle counters is required to exempt a server."""
    summary, server = metrics.get("summary", {}), metrics.get("server", {})
    counters = [summary.get("in_flight"), server.get("request_queue_depth"), server.get("audio_queue_depth")]
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in counters):
        return "active"
    if not all(zero(v) for v in counters) or health.get("status") != "healthy":
        return "unknown"
    for source in (health, server):
        if ("loaded_model" not in source or not isinstance(source.get("loaded_models"), dict)
                or "loaded_adapter" not in source):
            return "unknown"
    if any(health[k] != server.get(k) for k in ("loaded_model", "loaded_models", "loaded_adapter")):
        return "unknown"  # Evidence raced a model change.
    if server.get("preload_failures"):
        return "unknown"
    if not health["loaded_models"] and health["loaded_model"] is None and health["loaded_adapter"] is None:
        return "unloaded_idle"
    if health["loaded_models"] and isinstance(health["loaded_model"], str) and health["loaded_model"]:
        return "loaded_idle"
    return "unknown"


def probe_vlm(name, pid, read=api):
    base = URLS[name]
    try:
        health = read("GET", base + "/health")
        metrics = read("GET", base + "/metrics")
        return {"name": name, "pid": pid, "server_running": True,
                "state": classify_vlm(health, metrics), "health": health, "metrics": metrics}
    except Exception as exc:
        return {"name": name, "pid": pid, "server_running": True, "state": "unknown", "error": str(exc)}


def listener_matches(pid, port, command):
    result = command(["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-iTCP:" + str(port),
                      "-sTCP:LISTEN", "-Fp"])
    return f"p{pid}" in result.splitlines()


def conflicts(process_text, command, read=api):
    """Inspect known model servers/workers; unknown ports, activity and legacy contracts block."""
    observations = []
    for line in process_text.splitlines():
        try:
            first, args = line.strip().split(None, 1)
            pid = int(first)
            tokens = shlex.split(args)
        except (ValueError, IndexError):
            continue
        if pid == os.getpid():
            continue
        # Inspect actual interpreter/script arguments, not arbitrary text in a shell -c command.
        executable = os.path.basename(tokens[0])
        if not (executable.lower().startswith("python") or executable in {"uvicorn", "mlx-serve", "mlx_vlm"}):
            continue
        def port_value():
            try:
                if "--port" in tokens:
                    return int(tokens[tokens.index("--port") + 1])
                return next(int(t.split("=", 1)[1]) for t in tokens if t.startswith("--port="))
            except (ValueError, IndexError, StopIteration):
                return None
        port = port_value()
        module = tokens[tokens.index("-m") + 1] if "-m" in tokens and tokens.index("-m") + 1 < len(tokens) else ""
        vlm = (any(tokens[i] == "-m" and tokens[i+1] in {"mlx_vlm", "mlx_vlm.server"}
                   for i in range(len(tokens)-1)) or executable == "mlx_vlm")
        scripts = {os.path.basename(t) for t in tokens}
        if vlm:
            name = VLM.get(port)
            if name is None or not listener_matches(pid, port, command):
                observations.append({"name": name or "unknown_vlm", "pid": pid, "state": "unknown",
                                     "reason": "VLM port/PID ownership not verified"})
            else:
                row = probe_vlm(name, pid, read)
                row["startup_dependencies"] = [tokens[i+1] for i in range(len(tokens)-1)
                                                 if tokens[i] in {"--draft-model"}]
                row["startup_dependencies"] += [t.split("=", 1)[1] for t in tokens if t.startswith("--draft-model=")]
                observations.append(row)
            continue
        kind = None
        if any(t.startswith("image_service") for t in tokens):
            kind = "image"
        elif any(t.startswith("video_service") for t in tokens):
            kind = "video"
        elif "speech.entrypoint:app" in tokens:
            kind = "speech"
        elif "server:app" in tokens:
            kind = "musetalk"
        elif executable == "mlx-serve":
            kind = "mlxserve"
        elif (scripts & {"video_mlx_worker.py", "ltx2_server.py", "ltx-talking-photo-a2v.py",
                         "sdxl_worker.py", "image_worker.py", "mlxserve_image_worker.py"}
              or module.startswith(("ltx_lab.runner", "mflux", "mlx_lm", "ltx_core_mlx", "ltx_pipelines_mlx"))):
            observations.append({"name": "gpu_worker", "pid": pid, "state": "unknown",
                                 "reason": "Other GPU worker; activity cannot be ruled out"})
        if kind:
            expected = {"image": 8030, "video": 8060, "speech": 8050, "musetalk": 8070, "mlxserve": 11234}[kind]
            observation = {"name": kind, "pid": pid, "state": "unknown", "server_running": True}
            try:
                if port != expected or not listener_matches(pid, port, command):
                    raise ValueError("Service port/PID ownership not verified")
                health = read("GET", f"http://127.0.0.1:{port}" + ("/props" if kind == "mlxserve" else "/health"))
                observation["health"] = health
                if kind == "mlxserve":
                    active = health.get("memory", {}).get("active_bytes")
                    if (health.get("batching", {}).get("reason") == "no_model"
                            and isinstance(active, (int, float)) and not isinstance(active, bool)
                            and math.isfinite(active) and 0 <= active <= 4096):
                        observation["state"] = "unloaded_idle"
                elif health.get("active_generation") is True or health.get("active_job_id"):
                    observation["state"] = "active"
                elif health.get("active_generation") is False:
                    fields = ("loaded", "tts_loaded", "tts_clone_loaded") if kind == "speech" else ("loaded",)
                    if kind == "video":
                        observation["state"] = "unloaded_idle"  # Any separate worker is checked above.
                    elif all(health.get(k) is False for k in fields):
                        observation["state"] = "unloaded_idle"
                    elif any(health.get(k) is True for k in fields):
                        observation["state"] = "loaded_idle"
                if observation["state"] == "unknown":
                    observation["reason"] = "Missing/ambiguous model residency or inference status"
            except Exception as exc:
                observation["reason"] = str(exc)
            observations.append(observation)
    return observations
