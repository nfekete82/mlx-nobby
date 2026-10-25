"""Content-free monotonic phase timings for the native Juggernaut/SDXL worker.

No imported ML frameworks, file paths or user prompts are retained.
"""
from __future__ import annotations

import math
import time


class SDXLPhaseTimer:
    MARKS = frozenset({
        "model_ready", "inference_started", "first_step",
        "last_step", "inference_finished", "saved",
    })

    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.start = self.clock()
        self.points = {}

    def mark(self, name):
        if name not in self.MARKS:
            raise ValueError("Unsupported SDXL phase")
        self.points.setdefault(name, self.clock())

    def _ms(self, a, b):
        start = self.start if a == "start" else self.points.get(a)
        end = self.points.get(b)
        if start is None or end is None:
            return None
        elapsed = (end - start) * 1000
        return round(elapsed, 1) if math.isfinite(elapsed) and elapsed >= 0 else None

    def report(self, *, cold_model, steps, width=None, height=None, guidance=None):
        return {
            "provider": "sdxl",
            "cold_model": bool(cold_model),
            "worker_total_ms": self._ms("start", "saved"),
            "model_prepare_ms": self._ms("start", "model_ready"),
            "pipeline_setup_ms": self._ms("model_ready", "inference_started"),
            # First step includes initial inference dispatch; the window
            # excludes the first denoising step, avoiding false step claims.
            "first_step_ms": self._ms("inference_started", "first_step"),
            "denoise_window_ms": self._ms("first_step", "last_step"),
            # Best-effort post-last-callback phase including VAE decoding.
            "decode_finish_ms": self._ms("last_step", "inference_finished"),
            "image_save_ms": self._ms("inference_finished", "saved"),
            "steps": steps,
            "width": width,
            "height": height,
            "guidance": guidance,
        }
