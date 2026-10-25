"""Small monotonic image job timing helper; no prompts, paths or memory policy changes."""
from __future__ import annotations

import math
import time


class ImageJobTimings:
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.start = self.clock()
        self.events = {}

    def mark(self, name):
        if name not in {
            "resources_acquired", "execution_started", "prepared",
            "provider_done", "result_ready", "sdxl_released",
            "execution_finished",
        }:
            raise ValueError("Unsupported timing milestone")
        self.events.setdefault(name, self.clock())

    def report(self):
        end = self.clock()
        resources = self.events.get("resources_acquired")
        execution_start = self.events.get("execution_started")
        execution_end = self.events.get("execution_finished")
        prepared = self.events.get("prepared")
        provider_done = self.events.get("provider_done")
        result_ready = self.events.get("result_ready")
        sdxl_released = self.events.get("sdxl_released")
        def duration(a, b):
            if a is None or b is None:
                return None
            seconds = (b - a) * 1000
            return round(seconds, 1) if math.isfinite(seconds) and seconds >= 0 else None
        return {
            "schema": 1,
            "total_ms": duration(self.start, end),
            "resource_wait_ms": duration(self.start, resources),
            "preparation_ms": duration(resources, execution_start),
            "execution_ms": duration(execution_start, execution_end),
            "finalization_ms": duration(execution_end, end),
            # These nonoverlapping phases partition execution_ms for
            # successful generation jobs. Null means no stage was observed.
            "render_setup_ms": duration(execution_start, prepared),
            "provider_and_setup_ms": duration(prepared, provider_done),
            "output_finalize_ms": duration(provider_done, result_ready),
            "sdxl_unload_ms": duration(result_ready, sdxl_released),
            "runtime_return_ms": duration(
                sdxl_released if sdxl_released is not None else result_ready,
                execution_end,
            ),
            "note": "Native image-service only; excludes agent queue and frontend. Provider stage includes image validation and optional quality processing; runtime_return_ms includes coordinator exit and optional chat restoration.",
        }
