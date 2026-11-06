"""Dedicated 4B model child supervisor, launched by a macOS LaunchAgent.

It owns ONLY the optional port-8011 process. Foreground chat, image/video,
model settings, and existing SQLite memories remain under their own owners.
"""
from __future__ import annotations

from collections import deque
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import runtime_coordinator as rc
from agent import dedicated_memory_model
from agent import memory_model_coordination as ctl

MODEL = Path.home() / "Models/router/Qwen3.5-4B-MLX-4bit"
PORT = 8011
TICK_SECONDS = 5
MIN_FREE_START_PERCENT = 25
MIN_FREE_KEEP_PERCENT = 16
LOAD_RESERVE_GB = 5.0
STARTUP_SECONDS = 120
BACKOFF_SECONDS = 20
IDLE_UNLOAD_SECONDS = 120


def probe_port():
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def model_ready():
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"http://127.0.0.1:{PORT}/v1/models", timeout=1
        ) as response:
            data = json.load(response).get("data", [])
        return any(isinstance(x, dict) and x.get("id") == str(MODEL) for x in data)
    except (OSError, ValueError, TypeError):
        return False


def valid_settings():
    try:
        cfg = dedicated_memory_model.settings()
    except (OSError, ValueError, dedicated_memory_model.MemoryModelError):
        return False
    return (cfg.get("mode") == "dedicated" and cfg.get("port") == PORT
            and cfg.get("model") == str(MODEL) and (MODEL / "config.json").is_file())


def should_load(snapshot, media_kind=None):
    if media_kind or not isinstance(snapshot, dict):
        return False
    if ctl.on_demand_enabled() and not (
        ctl.router_demand_active() or ctl.memory_demand_active()
    ):
        return False
    free = snapshot.get("free_percent")
    if type(free) not in (float, int) or free < MIN_FREE_START_PERCENT:
        return False
    return not rc.projected_memory_hard_limit_reached(snapshot, LOAD_RESERVE_GB)


def should_unload(snapshot, media_kind=None, *, idle_expired=False):
    if not isinstance(snapshot, dict):
        return True
    free = snapshot.get("free_percent")
    if type(free) not in (float, int) or free < MIN_FREE_KEEP_PERCENT:
        return True
    if not media_kind:
        return bool(ctl.on_demand_enabled() and idle_expired
                    and not ctl.router_demand_active()
                    and not ctl.memory_demand_active())
    # Explicit heavy image generation must have exclusive unified-memory
    # headroom even when the previous light-weight memory probe looked safe.
    if ctl.exclusive_media_requested(media_kind):
        return True
    reserve = rc.model_load_reserve_gb(media_kind)
    min_headroom = (rc.VIDEO_MIN_HEADROOM_GB if media_kind == "video"
                    else rc.MEDIA_MIN_HEADROOM_GB)
    return (rc.memory_relief_needed(snapshot, min_headroom_gb=min_headroom)
            or rc.projected_memory_hard_limit_reached(snapshot, reserve))


class Supervisor:
    def __init__(self):
        self.child = None
        self.started_at = 0.0
        self.retry_at = 0.0
        self.stopping = False
        self.ready_reported = False
        self.media_pause_started = None
        self.idle_since = None
        # Session-only bounded numeric metrics. No checkpoint paths or prompts.
        self.samples = {
            key: deque(maxlen=32)
            for key in ("model_api_ready_ms", "model_unload_ms", "media_resume_ms")
        }

    def record(self, key, duration_ms):
        if (key in self.samples and type(duration_ms) in (float, int)
                and math.isfinite(duration_ms) and 0 <= duration_ms <= 3_600_000):
            self.samples[key].append(round(duration_ms, 2))

    def performance(self):
        result = {}
        for key, window in self.samples.items():
            values = sorted(window)
            if not values:
                result[key] = {"count": 0, "latest": None, "p50": None, "p95": None}
                continue

            def percentile(fraction):
                pos = (len(values) - 1) * fraction
                low = int(pos)
                high = min(len(values) - 1, low + 1)
                return round(values[low] + (values[high] - values[low]) * (pos - low), 2)

            result[key] = {
                "count": len(values),
                "latest": round(window[-1], 2),
                "p50": percentile(0.5),
                "p95": percentile(0.95),
            }
        return result

    def publish(self, state, *, pause=False):
        ctl._write(ctl.STATE, {
            "state": state,
            "owned": bool(self.child and self.child.poll() is None),
            "pause_extraction": bool(pause),
            "updated_at": time.time(),
            "performance": self.performance(),
        })

    def start(self):
        if self.child or probe_port() or time.monotonic() < self.retry_at:
            return
        ctl.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(ctl.ROOT / "model-server.log",
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            self.child = subprocess.Popen(
                [sys.executable, "-m", "mlx_vlm", "server", "--model", str(MODEL),
                 "--host", "127.0.0.1", "--port", str(PORT),
                 "--prefill-step-size", "512", "--max-num-seqs", "1"],
                stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                start_new_session=True, close_fds=True,
            )
            self.started_at = time.monotonic()
            self.ready_reported = False
            self.publish("starting", pause=True)
        finally:
            os.close(fd)

    def stop(self):
        if self.child is None:
            return True
        fd = os.open(ctl.LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            # A currently executing extraction owns a shared inference lease.
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            if self.child.poll() is None:
                unload_started = time.monotonic()
                self.child.terminate()
                try:
                    self.child.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=5)
                self.record("model_unload_ms",
                            (time.monotonic() - unload_started) * 1000)
            self.child = None
            self.ready_reported = False
            self.idle_since = None
            self.retry_at = time.monotonic() + BACKOFF_SECONDS
            return True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def tick(self):
        if self.child and self.child.poll() is not None:
            self.child = None
            self.ready_reported = False
            self.retry_at = time.monotonic() + BACKOFF_SECONDS
        if not valid_settings():
            if self.child:
                self.publish("draining", pause=True)
                if not self.stop():
                    return
            self.publish("disabled")
            return
        if not self.child and probe_port():
            # Manually started 4B server: report it, but NEVER terminate it.
            self.publish("external")
            return
        snap = rc.memory_budget_snapshot()
        kind = ctl.active_media_kind()
        if self.child:
            demand = ctl.router_demand_active() or ctl.memory_demand_active()
            if demand or not ctl.on_demand_enabled():
                self.idle_since = None
            elif self.idle_since is None:
                self.idle_since = time.monotonic()
            expired = (self.idle_since is not None
                       and time.monotonic() - self.idle_since >= IDLE_UNLOAD_SECONDS)
            if should_unload(snap, kind, idle_expired=expired):
                self.publish("draining", pause=True)
                if self.stop():
                    self.media_pause_started = time.monotonic() if kind else None
                    self.publish("suspended_media" if kind else "suspended_pressure", pause=True)
                else:
                    self.publish("draining", pause=True)
                return
            if time.monotonic() - self.started_at > STARTUP_SECONDS and not model_ready():
                if self.stop():
                    self.publish("startup_failed", pause=True)
                    return
            ready = model_ready()
            if ready and not self.ready_reported:
                self.record("model_api_ready_ms",
                            (time.monotonic() - self.started_at) * 1000)
                if self.media_pause_started is not None:
                    self.record("media_resume_ms",
                                (time.monotonic() - self.media_pause_started) * 1000)
                    self.media_pause_started = None
                self.ready_reported = True
            self.publish("running" if ready else "starting", pause=not ready)
            return
        if should_load(snap, kind):
            self.start()
            if self.child:
                return
        self.publish("suspended_media" if kind else "waiting_for_memory", pause=True)

    def run(self):
        def exiting(_signal, _frame):
            self.stopping = True
        signal.signal(signal.SIGTERM, exiting)
        signal.signal(signal.SIGINT, exiting)
        try:
            while not self.stopping:
                try:
                    self.tick()
                except Exception:
                    self.publish("supervisor_error", pause=True)
                for _ in range(TICK_SECONDS * 5):
                    if self.stopping:
                        break
                    time.sleep(0.2)
        finally:
            # Current inference must finish before stopping an owned child.
            while self.child is not None and not self.stop():
                time.sleep(0.3)
            self.publish("disabled")


if __name__ == "__main__":
    Supervisor().run()
