#!/usr/bin/env python3
"""Persistent local LTX 2.5 MLX worker for MLX Nobby.

The worker deliberately keeps only the Python/MLX process and pipeline object
warm between jobs. Upstream low-memory generation frees transformer, encoders,
upsampler, and decoders after each completed request, so the idle worker does
not pin the full video model while chat is restored.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ltx_pipelines_mlx.distilled import DistilledPipeline
from video_profiles import prepare_uncensored_loras, request_loras

HOST = os.environ.get("LTX_MLX_WORKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("LTX_MLX_WORKER_PORT", "18061"))
TOKEN = os.environ.get("LTX_MLX_AUTH_TOKEN", "mlx-nobby-ltx-mlx-local")
MODEL_DIR = Path(os.environ["LTX_MLX_MODEL_DIR"]).expanduser().resolve()
LOW_RAM = os.environ.get("LTX_MLX_LOW_RAM", "1").strip().lower() not in {"0", "false", "no", "off"}
PARENT_PID = int(os.environ.get("LTX_MLX_PARENT_PID", "0") or 0)

_STATE_LOCK = threading.RLock()
_GENERATION_LOCK = threading.Lock()
_PIPELINE = None
_STATE = {
    "busy": False,
    "phase": "ready",
    "progress": 0.0,
    "current_step": None,
    "total_steps": None,
    "generation_count": 0,
    "pipeline_initialized": False,
    "last_elapsed_seconds": None,
    "last_error": None,
}


def _pipeline():
    global _PIPELINE
    with _STATE_LOCK:
        if _PIPELINE is None:
            pipe = DistilledPipeline(
                model_dir=str(MODEL_DIR),
                gemma_model_id=str(MODEL_DIR),
                low_memory=True,
                low_ram_streaming=LOW_RAM,
            )
            pipe.verbose = False
            pipe.generate_audio = True
            _PIPELINE = pipe
            _STATE["pipeline_initialized"] = True
        return _PIPELINE


def _snapshot():
    with _STATE_LOCK:
        return dict(_STATE) | {
            "ok": True,
            "model": MODEL_DIR.name,
            "low_ram": LOW_RAM,
            "pid": os.getpid(),
            "weights_resident": False,
        }


def _install_progress_hook(pipe, stage1_steps, stage2_steps):
    """Map upstream per-step denoising callbacks onto worker health state.

    LTX 2.5 distilled generation is two-stage (8 + 3 steps for normal
    quality). Denoising occupies 90% of the public progress range so the UI
    never claims 100% while decode/audio muxing is still running.
    """
    total_steps = max(1, int(stage1_steps) + int(stage2_steps))

    def stepwise_hook(_latent_frames, _latent_height, _latent_width, *, stage=None):
        stage_offset = int(stage1_steps) if stage == 2 else 0

        def on_step(step_idx, num_steps, _video_x0, _sigma):
            completed_in_stage = min(int(step_idx) + 1, max(1, int(num_steps)))
            completed = min(total_steps, stage_offset + completed_in_stage)
            with _STATE_LOCK:
                _STATE.update(
                    phase="denoising",
                    current_step=completed,
                    total_steps=total_steps,
                    progress=round(0.9 * completed / total_steps, 6),
                )

        return on_step

    # The pinned upstream pipeline asks self._stepwise_hook(...) separately for
    # stage 1 and stage 2. Replacing the instance hook is intentionally local to
    # this worker and avoids patching the installed upstream runtime.
    pipe._stepwise_hook = stepwise_hook


def _generate(payload):
    global _PIPELINE
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise RuntimeError("LTX-MLX worker is already generating")
    started = time.monotonic()
    pipe = _PIPELINE
    succeeded = False
    with _STATE_LOCK:
        reused = _STATE["generation_count"] > 0
        _STATE.update(
            busy=True,
            phase="generating",
            progress=0.01,
            current_step=0,
            total_steps=None,
            last_error=None,
        )
    try:
        if pipe is not None:
            pipe._pending_loras = []
        loras = request_loras(payload.get("profile", "standard"))
        prepare_uncensored_loras(loras)
        stage1_steps = int(payload["stage1_steps"])
        stage2_steps = int(payload["stage2_steps"])
        total_steps = max(1, stage1_steps + stage2_steps)
        with _STATE_LOCK:
            _STATE["total_steps"] = total_steps
        output = Path(str(payload["output"])).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        image = payload.get("image")
        pipe = _pipeline()
        pipe._pending_loras = []
        pipe._pending_loras = loras
        _install_progress_hook(pipe, stage1_steps, stage2_steps)
        pipe.generate_and_save(
            prompt=str(payload["prompt"]),
            output_path=str(output),
            height=int(payload["height"]),
            width=int(payload["width"]),
            num_frames=int(payload["frames"]),
            frame_rate=float(payload["fps"]),
            seed=int(payload["seed"]),
            stage1_steps=stage1_steps,
            stage2_steps=stage2_steps,
            image=str(image) if image else None,
        )
        if not output.is_file():
            raise RuntimeError("LTX-MLX worker produced no video")
        elapsed = time.monotonic() - started
        succeeded = True
        with _STATE_LOCK:
            _STATE["generation_count"] += 1
            _STATE.update(
                busy=False,
                phase="ready",
                progress=1.0,
                current_step=total_steps,
                total_steps=total_steps,
                last_elapsed_seconds=round(elapsed, 3),
            )
        return {
            "ok": True,
            "runtime_reused": reused,
            "elapsed_seconds": round(elapsed, 3),
            "output": str(output),
        }
    except Exception as exc:
        with _STATE_LOCK:
            _STATE.update(
                busy=False,
                phase="ready",
                progress=0.0,
                current_step=None,
                total_steps=None,
                last_error=str(exc)[-2000:],
            )
        raise
    finally:
        if pipe is not None:
            pipe._pending_loras = []
        if not succeeded:
            # Upstream frees loaded weights on success only. Discard a failed
            # pipeline so a later request cannot reuse adapter-bearing weights.
            with _STATE_LOCK:
                _PIPELINE = None
                _STATE["pipeline_initialized"] = False
                _STATE.update(busy=False, phase="ready")
        _GENERATION_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "mlx-nobby-ltx-mlx/3"

    def log_message(self, fmt, *args):
        return

    def _authorized(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        if self.path == "/health":
            self._json(200, _snapshot())
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._authorized():
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        if self.path == "/generate":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._json(200, _generate(payload))
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)[-4000:]})
            return
        if self.path == "/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json(404, {"ok": False, "error": "not found"})


def _watch_parent():
    if PARENT_PID <= 1:
        return
    while True:
        time.sleep(2)
        try:
            os.kill(PARENT_PID, 0)
        except OSError:
            os._exit(0)


def main():
    if not MODEL_DIR.is_dir():
        raise SystemExit(f"LTX-MLX model directory missing: {MODEL_DIR}")
    threading.Thread(target=_watch_parent, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
