"""Experimental Wan 2.2 TI2V 5B provider using native MLX.

The provider intentionally stays separate from the LTX paths.  It uses a pinned
`mlx-video` runtime and a pre-converted q8 checkpoint so Nobby can benchmark a
smaller 5B video model on Apple Silicon without changing the current default.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import video_registry
from video_providers import (
    ProviderCancelled,
    _prepare_first_frame,
    _probe_video,
    validate_first_frame,
)


WAN_RUNTIME_ROOT = Path(os.environ.get(
    "WAN_MLX_RUNTIME_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/wan22-mlx"),
)).expanduser()
WAN_PYTHON = Path(os.environ.get(
    "WAN_MLX_PYTHON",
    str(WAN_RUNTIME_ROOT / ".venv/bin/python"),
)).expanduser()
WAN_MODEL_ROOT = Path(os.environ.get(
    "WAN_MLX_MODEL_ROOT",
    str(Path.home() / ".local/share/mlx-nobby/models"),
)).expanduser()
WAN_LOG = Path.home() / ".config/mlx-web/wan-runtime.log"
WAN_MODULE = "mlx_video.models.wan_2.generate"
WAN_GUIDE_SCALE = 5.0
WAN_SHIFT = 5.0
WAN_SCHEDULER = "unipc"
MEMORY_SAMPLE_INTERVAL = 5.0


@dataclass
class WanRuntime:
    process: subprocess.Popen
    log: object


def owns_runtime(runtime):
    return isinstance(runtime, WanRuntime)


def _model_path(model):
    return WAN_MODEL_ROOT / str(model.get("id") or video_registry.WAN_MLX_Q8_ID)


def availability(model):
    if str(model.get("provider") or "") != "wan-mlx":
        return False, "Kein Wan-MLX-Modell"
    if not WAN_PYTHON.is_file() or not os.access(WAN_PYTHON, os.X_OK):
        return False, f"Wan-MLX-Runtime fehlt unter {WAN_RUNTIME_ROOT}"
    if not video_registry.local_files_available(model):
        missing = video_registry.missing_files(model)
        return False, "Wan-2.2-TI2V-5B-MLX-Q8-Dateien fehlen: " + ", ".join(missing)
    return True, "Wan 2.2 TI2V 5B Q8 ist nativ über MLX/Metal verfügbar (experimentell)"


def _terminate(runtime):
    if not owns_runtime(runtime):
        return
    process = runtime.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    try:
        if not runtime.log.closed:
            runtime.log.close()
    except Exception:
        pass


def unload(runtime):
    _terminate(runtime)


def warm_runtime_status():
    return {
        "loaded": False,
        "idle_timeout_seconds": 0,
        "backend": "wan-mlx-cli",
        "model": video_registry.WAN_MLX_Q8_ID,
    }


def _command(model, params, output, *, image=None):
    if params.get("quality") == "preview":
        raise ValueError("Wan 2.2 5B unterstützt in Nobby noch keinen Preview-Modus")
    if int(params.get("fps") or 24) != 24:
        raise ValueError("Wan 2.2 TI2V 5B wird lokal mit 24 fps betrieben")

    width = int(params["width"])
    height = int(params["height"])
    frames = int(params["frames"])
    if width % 32 or height % 32:
        raise ValueError("Wan 2.2 TI2V 5B benötigt durch 32 teilbare Abmessungen")
    if (frames - 1) % 4:
        raise ValueError("Wan 2.2 TI2V 5B benötigt 4n+1 Frames")

    command = [
        str(WAN_PYTHON), "-m", WAN_MODULE,
        "--model-dir", str(_model_path(model)),
        "--prompt", str(params["prompt"]),
        "--width", str(width),
        "--height", str(height),
        "--num-frames", str(frames),
        "--steps", str(int(params["steps"])),
        "--guide-scale", str(WAN_GUIDE_SCALE),
        "--shift", str(WAN_SHIFT),
        "--scheduler", WAN_SCHEDULER,
        "--seed", str(int(params["seed"])),
        "--tiling", "auto",
        "--output-path", str(output),
    ]
    if image is not None:
        command.extend(["--image", str(image)])
    return command


def _tail_log(limit=4000):
    try:
        with WAN_LOG.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _runtime_environment():
    environment = os.environ.copy()
    environment.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def _run_process(command, *, cancel_event, response_callback=None,
                 progress_callback=None, phase_callback=None):
    WAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = WAN_LOG.open("ab", buffering=0)
    if phase_callback:
        phase_callback("loading")
    process = subprocess.Popen(
        command,
        cwd=WAN_RUNTIME_ROOT,
        env=_runtime_environment(),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    runtime = WanRuntime(process, log)
    if response_callback:
        response_callback(runtime)
    if phase_callback:
        phase_callback("generating")
    if progress_callback:
        progress_callback({"phase": "generating", "progress": 0.01})

    last_sample = time.monotonic()
    try:
        while process.poll() is None:
            if cancel_event.is_set():
                _terminate(runtime)
                raise ProviderCancelled("Video job was cancelled")
            now = time.monotonic()
            if progress_callback and now - last_sample >= MEMORY_SAMPLE_INTERVAL:
                # The service samples unified-memory/swap on every progress
                # callback.  Do this sparsely so the benchmark sees the real
                # peak without adding meaningful I/O overhead to inference.
                progress_callback({"phase": "generating"})
                last_sample = now
            time.sleep(0.5)
    finally:
        if response_callback:
            response_callback(None)

    returncode = process.returncode
    try:
        if not log.closed:
            log.close()
    except Exception:
        pass
    if returncode != 0:
        detail = _tail_log().strip()
        raise RuntimeError(
            "Wan-MLX-Worker fehlgeschlagen"
            + (f": {detail}" if detail else f" (Exit {returncode})")
        )


def generate(model, params, output, *, cancel_event, response_callback=None,
             progress_callback=None, phase_callback=None):
    ready, reason = availability(model)
    if not ready:
        raise RuntimeError(reason)

    source = validate_first_frame(params.get("first_frame"))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    resize_info = {}

    with tempfile.TemporaryDirectory(prefix="mlx-nobby-wan22-") as temporary:
        prepared = None
        if source is not None:
            prepared = Path(temporary) / "first-frame.png"
            width = int(params["width"])
            height = int(params["height"])
            resize_info = _prepare_first_frame(
                source,
                width,
                height,
                params.get("resize_mode") or "contain",
                prepared,
            )
            resize_info.update({
                "target_width": width,
                "target_height": height,
                "conditioning_width": width,
                "conditioning_height": height,
            })

        command = _command(model, params, output, image=prepared)
        _run_process(
            command,
            cancel_event=cancel_event,
            response_callback=response_callback,
            progress_callback=progress_callback,
            phase_callback=phase_callback,
        )

    if cancel_event.is_set():
        output.unlink(missing_ok=True)
        raise ProviderCancelled("Video job was cancelled")
    if not output.is_file():
        raise RuntimeError("Wan-MLX-Worker lieferte kein Video")

    if phase_callback:
        phase_callback("muxing")
    if progress_callback:
        progress_callback({"phase": "muxing", "progress": 0.98})

    elapsed = time.monotonic() - started
    return _probe_video(output) | resize_info | {
        "backend": "wan-mlx",
        "runtime_reused": False,
        "provider_elapsed_seconds": round(elapsed, 3),
        "provider_payload": {
            "mode": "wan2.2-ti2v-single-model",
            "quantization": str(model.get("quantization") or "int8"),
            "width": int(params["width"]),
            "height": int(params["height"]),
            "frames": int(params["frames"]),
            "fps": 24,
            "steps": int(params["steps"]),
            "guide_scale": WAN_GUIDE_SCALE,
            "shift": WAN_SHIFT,
            "scheduler": WAN_SCHEDULER,
            "image_to_video": source is not None,
            "audio": False,
        },
    }
