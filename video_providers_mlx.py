"""Experimental native-MLX LTX 2.5 provider with a warm worker process.

The stable LTX Desktop/MPS provider remains independent. Native MLX uses the
pinned ltx-2-mlx environment, but keeps its Python/MLX worker process alive for
short bursts of jobs. Upstream low-memory generation explicitly frees the heavy
transformer/encoder/decoder weights after every completed request, so warm reuse
does not pin the full model while chat is restored.
"""
from __future__ import annotations

import atexit
import concurrent.futures
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import video_registry
from video_providers import (
    ProviderCancelled,
    _prepare_first_frame,
    _probe_video,
    validate_first_frame,
)


LTX_MLX_RUNTIME_ROOT = Path(os.environ.get(
    "LTX_MLX_RUNTIME_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/ltx-2-mlx"),
)).expanduser()
LTX_MLX_PYTHON = Path(os.environ.get(
    "LTX_MLX_PYTHON",
    str(LTX_MLX_RUNTIME_ROOT / ".venv/bin/python"),
)).expanduser()
LTX_MLX_CLI = Path(os.environ.get(
    "LTX_MLX_CLI",
    str(LTX_MLX_RUNTIME_ROOT / ".venv/bin/ltx-2-mlx"),
)).expanduser()
LTX_MLX_WORKER = Path(__file__).resolve().with_name("video_mlx_worker.py")
LTX_MLX_URL = os.environ.get("LTX_MLX_WORKER_URL", "http://127.0.0.1:18061").rstrip("/")
LTX_MLX_AUTH_TOKEN = os.environ.get("LTX_MLX_AUTH_TOKEN", "mlx-nobby-ltx-mlx-local")
LTX_MLX_LOG = Path.home() / ".config/mlx-web/ltx-mlx-runtime.log"
DEFAULT_LOW_RAM = os.environ.get("LTX_MLX_LOW_RAM", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
PERSISTENT_WORKER = os.environ.get("LTX_MLX_PERSISTENT", "1").strip().lower() not in {
    "0", "false", "no", "off",
}
DEFAULT_IDLE_TIMEOUT = 300.0
_RUNTIME_LOCK = threading.RLock()
_GENERATION_LOCK = threading.Lock()
_WARM_RUNTIME = None
_WARM_TIMER = None
_WARM_GENERATION = 0


@dataclass
class MlxWarmRuntime:
    process: subprocess.Popen
    log: object
    model_path: Path


@dataclass
class MlxCliRuntime:
    process: subprocess.Popen


def owns_runtime(runtime):
    return isinstance(runtime, (MlxWarmRuntime, MlxCliRuntime))


def availability(model):
    if str(model.get("provider") or "") != "ltx-mlx":
        return False, "Kein LTX-MLX-Modell"
    if not video_registry.local_files_available(model):
        missing = video_registry.missing_files(model)
        return False, "LTX-2.5-MLX-Q4-Gewichte fehlen: " + ", ".join(missing)
    if PERSISTENT_WORKER:
        if not LTX_MLX_PYTHON.is_file() or not os.access(LTX_MLX_PYTHON, os.X_OK):
            return False, f"LTX-MLX-Python fehlt: {LTX_MLX_PYTHON}"
        if not LTX_MLX_WORKER.is_file():
            return False, f"LTX-MLX-Worker fehlt: {LTX_MLX_WORKER}"
    else:
        if not LTX_MLX_CLI.is_file() or not os.access(LTX_MLX_CLI, os.X_OK):
            return False, f"LTX-MLX-CLI fehlt: {LTX_MLX_CLI}"
    mode = "persistenter MLX-Worker" if PERSISTENT_WORKER else "MLX-CLI"
    return True, f"LTX 2.5 Q4 ist nativ über MLX/Metal verfügbar ({mode}, experimentell)"


def _worker_headers():
    return {
        "Authorization": f"Bearer {LTX_MLX_AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _json_request(method, path, payload=None, timeout=30):
    request = urllib.request.Request(
        LTX_MLX_URL + path,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=_worker_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LTX-MLX worker HTTP {exc.code}: {detail[-3000:]}") from exc


def _terminate_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _configured_idle_timeout():
    try:
        value = float(os.environ.get("MLX_VIDEO_MLX_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_TIMEOUT
    return value if value > 0 else DEFAULT_IDLE_TIMEOUT


def _worker_endpoint():
    parsed = urllib.parse.urlsplit(LTX_MLX_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 18061
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("LTX_MLX_WORKER_URL muss auf einen lokalen HTTP-Endpunkt zeigen")
    return host, port


def _runtime_alive(runtime):
    if not isinstance(runtime, MlxWarmRuntime) or runtime.process.poll() is not None:
        return False
    try:
        health = _json_request("GET", "/health", timeout=2)
        return bool(health.get("ok"))
    except Exception:
        return False


def _start_runtime(model, cancel_event):
    host, port = _worker_endpoint()
    LTX_MLX_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = LTX_MLX_LOG.open("ab", buffering=0)
    environment = os.environ.copy()
    environment.update({
        "LTX_MLX_WORKER_HOST": host,
        "LTX_MLX_WORKER_PORT": str(port),
        "LTX_MLX_AUTH_TOKEN": LTX_MLX_AUTH_TOKEN,
        "LTX_MLX_MODEL_DIR": str(video_registry.model_path(model)),
        "LTX_MLX_LOW_RAM": "1" if DEFAULT_LOW_RAM else "0",
        "LTX_MLX_PARENT_PID": str(os.getpid()),
    })
    process = subprocess.Popen(
        [str(LTX_MLX_PYTHON), str(LTX_MLX_WORKER)],
        cwd=LTX_MLX_RUNTIME_ROOT,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    runtime = MlxWarmRuntime(process=process, log=log, model_path=video_registry.model_path(model))
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            if cancel_event.is_set():
                raise ProviderCancelled("Video job was cancelled")
            if process.poll() is not None:
                raise RuntimeError(f"LTX-MLX-Worker wurde unerwartet beendet (Exit {process.returncode})")
            try:
                if _json_request("GET", "/health", timeout=2).get("ok"):
                    return runtime
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("LTX-MLX-Worker wurde nicht rechtzeitig bereit")
    except Exception:
        _stop_runtime(runtime)
        raise


def _stop_runtime(runtime):
    if not isinstance(runtime, MlxWarmRuntime):
        return
    if runtime.process.poll() is None:
        try:
            _json_request("POST", "/shutdown", {}, timeout=2)
            runtime.process.wait(timeout=3)
        except Exception:
            _terminate_process(runtime.process)
    if not runtime.log.closed:
        runtime.log.close()


def _cancel_warm_timer_locked():
    global _WARM_TIMER, _WARM_GENERATION
    _WARM_GENERATION += 1
    if _WARM_TIMER is not None:
        _WARM_TIMER.cancel()
        _WARM_TIMER = None


def _stop_warm_runtime_locked():
    global _WARM_RUNTIME
    _cancel_warm_timer_locked()
    runtime = _WARM_RUNTIME
    _WARM_RUNTIME = None
    if runtime is not None:
        _stop_runtime(runtime)


def _expire_warm_runtime(generation):
    with _RUNTIME_LOCK:
        if generation == _WARM_GENERATION:
            _stop_warm_runtime_locked()


def _schedule_warm_shutdown_locked():
    global _WARM_TIMER
    _cancel_warm_timer_locked()
    generation = _WARM_GENERATION
    timer = threading.Timer(_configured_idle_timeout(), _expire_warm_runtime, args=(generation,))
    timer.daemon = True
    _WARM_TIMER = timer
    timer.start()


def _acquire_runtime(model, cancel_event):
    global _WARM_RUNTIME
    model_path = video_registry.model_path(model)
    with _RUNTIME_LOCK:
        _cancel_warm_timer_locked()
        if _runtime_alive(_WARM_RUNTIME) and _WARM_RUNTIME.model_path == model_path:
            return _WARM_RUNTIME, True
        if _WARM_RUNTIME is not None:
            _stop_warm_runtime_locked()
        _WARM_RUNTIME = _start_runtime(model, cancel_event)
        return _WARM_RUNTIME, False


def discard_runtime(runtime):
    if isinstance(runtime, MlxCliRuntime):
        _terminate_process(runtime.process)
        return
    if not isinstance(runtime, MlxWarmRuntime):
        return
    with _RUNTIME_LOCK:
        if runtime is _WARM_RUNTIME:
            _stop_warm_runtime_locked()
        else:
            _stop_runtime(runtime)


def unload(runtime):
    """Keep a healthy idle worker briefly; heavy weights are already released."""
    if isinstance(runtime, MlxCliRuntime):
        _terminate_process(runtime.process)
        return
    if not isinstance(runtime, MlxWarmRuntime):
        return
    with _RUNTIME_LOCK:
        if runtime is _WARM_RUNTIME and _runtime_alive(runtime):
            _schedule_warm_shutdown_locked()
        elif runtime is _WARM_RUNTIME:
            _stop_warm_runtime_locked()
        else:
            _stop_runtime(runtime)


def shutdown_warm_runtime():
    with _RUNTIME_LOCK:
        _stop_warm_runtime_locked()


def warm_runtime_status():
    with _RUNTIME_LOCK:
        runtime = _WARM_RUNTIME
        loaded = _runtime_alive(runtime)
        health = {}
        if loaded:
            try:
                health = _json_request("GET", "/health", timeout=2)
            except Exception:
                health = {}
        return {
            "loaded": loaded,
            "idle_timeout_seconds": _configured_idle_timeout(),
            "backend": "mlx-worker" if PERSISTENT_WORKER else "mlx-cli",
            "model": runtime.model_path.name if loaded and runtime else None,
            "requests_completed": int(health.get("generation_count") or 0),
            "busy": bool(health.get("busy")),
            "weights_resident": bool(health.get("weights_resident")),
        }


atexit.register(shutdown_warm_runtime)


def _command(model, params, output, *, image=None):
    profile_stage_1 = 1 if params.get("quality") == "preview" else 8
    profile_stage_2 = 1 if params.get("quality") == "preview" else 3
    command = [
        str(LTX_MLX_CLI), "generate", "--distilled",
        "--prompt", str(params["prompt"]), "--output", str(output),
        "--model", str(video_registry.model_path(model)),
        "--width", str(int(params["width"])), "--height", str(int(params["height"])),
        "--frames", str(int(params["frames"])), "--frame-rate", str(float(params["fps"])),
        "--seed", str(int(params["seed"])),
        "--stage1-steps", str(profile_stage_1), "--stage2-steps", str(profile_stage_2),
    ]
    if DEFAULT_LOW_RAM:
        command.append("--low-ram")
    if image is not None:
        command.extend(["--image", str(image)])
    return command


def _run_process(command, *, cancel_event, response_callback=None,
                 progress_callback=None, phase_callback=None):
    if phase_callback:
        phase_callback("loading")
    process = subprocess.Popen(
        command, cwd=LTX_MLX_RUNTIME_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    runtime = MlxCliRuntime(process)
    if response_callback:
        response_callback(runtime)
    if phase_callback:
        phase_callback("generating")
    if progress_callback:
        progress_callback({"phase": "generating", "progress": 0.01})
    output = ""
    try:
        while True:
            if cancel_event.is_set():
                _terminate_process(process)
                raise ProviderCancelled("Video job was cancelled")
            try:
                stdout, _ = process.communicate(timeout=0.5)
                output = stdout or ""
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if response_callback:
            response_callback(None)
    if process.returncode != 0:
        detail = output[-4000:].strip()
        raise RuntimeError("LTX-MLX-Worker fehlgeschlagen" + (f": {detail}" if detail else f" (Exit {process.returncode})"))
    return output


def _run_warm_worker(model, params, output, *, image, cancel_event,
                     response_callback=None, progress_callback=None, phase_callback=None):
    with _GENERATION_LOCK:
        runtime, runtime_reused = _acquire_runtime(model, cancel_event)
        if response_callback:
            response_callback(runtime)
        succeeded = False
        try:
            if phase_callback:
                phase_callback("generating")
            payload = {
                "prompt": str(params["prompt"]),
                "output": str(output),
                "width": int(params["width"]),
                "height": int(params["height"]),
                "frames": int(params["frames"]),
                "fps": float(params["fps"]),
                "seed": int(params["seed"]),
                "stage1_steps": 1 if params.get("quality") == "preview" else 8,
                "stage2_steps": 1 if params.get("quality") == "preview" else 3,
                "image": str(image) if image is not None else None,
            }
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_json_request, "POST", "/generate", payload, 7200)
                while not future.done():
                    if cancel_event.is_set():
                        discard_runtime(runtime)
                        raise ProviderCancelled("Video job was cancelled")
                    try:
                        health = _json_request("GET", "/health", timeout=2)
                        phase = str(health.get("phase") or "generating")
                        if phase_callback:
                            phase_callback(phase)
                        if progress_callback:
                            progress_callback({
                                "phase": phase,
                                "progress": health.get("progress", 0.01),
                            })
                    except Exception:
                        if runtime.process.poll() is not None:
                            raise RuntimeError("LTX-MLX-Worker wurde während der Generierung beendet")
                    time.sleep(0.5)
                result = future.result()
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "LTX-MLX-Worker fehlgeschlagen"))
            succeeded = True
            return runtime_reused, result
        finally:
            if response_callback:
                response_callback(None)
            if succeeded:
                unload(runtime)
            else:
                discard_runtime(runtime)


def generate(model, params, output, *, cancel_event, response_callback=None,
             progress_callback=None, phase_callback=None):
    ready, reason = availability(model)
    if not ready:
        raise RuntimeError(reason)

    source = validate_first_frame(params.get("first_frame"))
    if params.get("quality") == "preview" and source is not None:
        raise ValueError("Video-Vorschau ist nur für Text-zu-Video verfügbar")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    resize_info = {}
    runtime_reused = False
    worker_result = {}

    with tempfile.TemporaryDirectory(prefix="mlx-nobby-ltx-mlx-") as temporary:
        prepared = None
        if source is not None:
            prepared = Path(temporary) / "first-frame.png"
            target_width = int(params["width"])
            target_height = int(params["height"])
            resize_info = _prepare_first_frame(
                source, target_width, target_height,
                params.get("resize_mode") or "contain", prepared,
            )
            resize_info.update({
                "target_width": target_width, "target_height": target_height,
                "conditioning_width": target_width, "conditioning_height": target_height,
            })

        if PERSISTENT_WORKER:
            runtime_reused, worker_result = _run_warm_worker(
                model, params, output, image=prepared, cancel_event=cancel_event,
                response_callback=response_callback, progress_callback=progress_callback,
                phase_callback=phase_callback,
            )
        else:
            command = _command(model, params, output, image=prepared)
            _run_process(
                command, cancel_event=cancel_event, response_callback=response_callback,
                progress_callback=progress_callback, phase_callback=phase_callback,
            )

    if cancel_event.is_set():
        output.unlink(missing_ok=True)
        raise ProviderCancelled("Video job was cancelled")
    if not output.is_file():
        raise RuntimeError("LTX-MLX-Worker lieferte kein Video")

    if phase_callback:
        phase_callback("muxing")
    if progress_callback:
        progress_callback({"phase": "muxing", "progress": 98})

    elapsed = time.monotonic() - started
    return _probe_video(output) | resize_info | {
        "backend": "mlx",
        "runtime_reused": runtime_reused,
        "provider_elapsed_seconds": round(elapsed, 3),
        "provider_payload": {
            "mode": "distilled-two-stage",
            "worker_mode": "persistent" if PERSISTENT_WORKER else "cli",
            "worker_elapsed_seconds": worker_result.get("elapsed_seconds"),
            "quantization": str(model.get("quantization") or "int4"),
            "width": int(params["width"]), "height": int(params["height"]),
            "frames": int(params["frames"]), "fps": int(params["fps"]),
            "stage_1_steps": 1 if params.get("quality") == "preview" else 8,
            "stage_2_steps": 1 if params.get("quality") == "preview" else 3,
            "low_ram": DEFAULT_LOW_RAM,
            "image_to_video": source is not None,
        },
    }
