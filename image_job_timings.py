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
        if name not in {"resources_acquired", "execution_started", "execution_finished"}:
            raise ValueError("Unsupported timing milestone")
        self.events.setdefault(name, self.clock())

    def report(self):
        end = self.clock()
        resources = self.events.get("resources_acquired")
        execution_start = self.events.get("execution_started")
        execution_end = self.events.get("execution_finished")
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
            "note": "Native image-service only; excludes agent queue and frontend; execution includes provider process and output work.",
        }
