"""Experimental native-MLX LTX 2.5 provider.

The implementation deliberately lives beside the proven LTX Desktop/MPS
provider. It shells out to a pinned ltx-2-mlx runtime so the experiment can be
benchmarked and removed independently without making MLX a hard dependency of
MLX Nobby's video service.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
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
LTX_MLX_CLI = Path(os.environ.get(
    "LTX_MLX_CLI",
    str(LTX_MLX_RUNTIME_ROOT / ".venv/bin/ltx-2-mlx"),
)).expanduser()
DEFAULT_LOW_RAM = os.environ.get("LTX_MLX_LOW_RAM", "1").strip().lower() not in {
    "0", "false", "no", "off",
}


def owns_runtime(runtime):
    return isinstance(runtime, subprocess.Popen)


def availability(model):
    if str(model.get("provider") or "") != "ltx-mlx":
        return False, "Kein LTX-MLX-Modell"
    if not LTX_MLX_CLI.is_file():
        return False, f"LTX-MLX-Runtime fehlt unter {LTX_MLX_RUNTIME_ROOT}"
    if not os.access(LTX_MLX_CLI, os.X_OK):
        return False, f"LTX-MLX-CLI ist nicht ausführbar: {LTX_MLX_CLI}"
    if not video_registry.local_files_available(model):
        missing = video_registry.missing_files(model)
        return False, "LTX-2.5-MLX-Q4-Gewichte fehlen: " + ", ".join(missing)
    return True, "LTX 2.5 Q4 ist nativ über MLX/Metal verfügbar (experimentell)"


def _terminate(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def unload(runtime):
    """Terminate an active CLI runtime during service shutdown/cancellation."""
    if owns_runtime(runtime):
        _terminate(runtime)


def _command(model, params, output, *, image=None):
    profile_stage_1 = 1 if params.get("quality") == "preview" else 8
    profile_stage_2 = 1 if params.get("quality") == "preview" else 3
    command = [
        str(LTX_MLX_CLI),
        "generate",
        "--distilled",
        "--prompt", str(params["prompt"]),
        "--output", str(output),
        "--model", str(video_registry.model_path(model)),
        # LTX 2.5 MLX packs ship their Gemma 4 text encoder inside the pack;
        # ltx-2-mlx auto-selects it from text_encoder*. Do not force its
        # Gemma-3 fallback with an unnecessary second checkpoint.
        "--width", str(int(params["width"])),
        "--height", str(int(params["height"])),
        "--frames", str(int(params["frames"])),
        "--frame-rate", str(float(params["fps"])),
        "--seed", str(int(params["seed"])),
        "--stage1-steps", str(profile_stage_1),
        "--stage2-steps", str(profile_stage_2),
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
        command,
        cwd=LTX_MLX_RUNTIME_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if response_callback:
        response_callback(process)
    if phase_callback:
        phase_callback("generating")
    if progress_callback:
        progress_callback({"phase": "generating", "progress": 0.01})

    output = ""
    try:
        while True:
            if cancel_event.is_set():
                _terminate(process)
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
        raise RuntimeError(
            "LTX-MLX-Worker fehlgeschlagen"
            + (f": {detail}" if detail else f" (Exit {process.returncode})")
        )
    return output


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

    with tempfile.TemporaryDirectory(prefix="mlx-nobby-ltx-mlx-") as temporary:
        prepared = None
        if source is not None:
            prepared = Path(temporary) / "first-frame.png"
            target_width = int(params["width"])
            target_height = int(params["height"])
            resize_info = _prepare_first_frame(
                source,
                target_width,
                target_height,
                params.get("resize_mode") or "contain",
                prepared,
            )
            resize_info.update({
                "target_width": target_width,
                "target_height": target_height,
                "conditioning_width": target_width,
                "conditioning_height": target_height,
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
        raise RuntimeError("LTX-MLX-Worker lieferte kein Video")

    if phase_callback:
        phase_callback("muxing")
    if progress_callback:
        progress_callback({"phase": "muxing", "progress": 98})

    elapsed = time.monotonic() - started
    return _probe_video(output) | resize_info | {
        "backend": "mlx",
        "runtime_reused": False,
        "provider_elapsed_seconds": round(elapsed, 3),
        "provider_payload": {
            "mode": "distilled-two-stage",
            "quantization": str(model.get("quantization") or "int4"),
            "width": int(params["width"]),
            "height": int(params["height"]),
            "frames": int(params["frames"]),
            "fps": int(params["fps"]),
            "stage_1_steps": 1 if params.get("quality") == "preview" else 8,
            "stage_2_steps": 1 if params.get("quality") == "preview" else 3,
            "low_ram": DEFAULT_LOW_RAM,
            "image_to_video": source is not None,
        },
    }
