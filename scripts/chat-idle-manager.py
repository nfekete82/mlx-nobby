#!/usr/bin/env python3
"""Opt-in, fail-closed idle model reaper for MLX-VLM on localhost port 8000.

Does not stop processes, modify persistent memories or reload any services.
Default command is a read-only check; auto-unload requires explicit --apply.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import signal
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOST = "http://127.0.0.1"
DEFAULT_IDLE_SECONDS = 600
DEFAULT_POLL_SECONDS = 30


class ProbeUnavailable(RuntimeError):
    """Unavailable or ambiguous telemetry must never authorize unload."""


def _json_get(port: int, endpoint: str, *, timeout: float = 3.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"{HOST}:{port}{endpoint}", timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ProbeUnavailable(f"Malformed local endpoint: {port}{endpoint}")
    return data


def _number(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ProbeUnavailable(f"Missing/invalid nonnegative integer: {name}")
    return value


@dataclass(frozen=True)
class Snapshot:
    model: str | None
    requests_started: int
    in_flight: int
    queue_depth: int
    agent_runs: int
    last_request_at: object

    @property
    def idle(self) -> bool:
        return self.in_flight == 0 and self.queue_depth == 0 and self.agent_runs == 0

    @property
    def signature(self) -> tuple:
        # Opaque request-activity marker. No prompts or messages are logged.
        return self.model, self.requests_started, self.last_request_at


def probe() -> Snapshot:
    health = _json_get(8000, "/health")
    metrics = _json_get(8000, "/metrics")
    agent = _json_get(8010, "/api/runtime/reliability")
    summary, server = metrics.get("summary"), metrics.get("server")
    if health.get("status") != "healthy" or not isinstance(summary, dict) or not isinstance(server, dict):
        raise ProbeUnavailable("Chat health/metrics unavailable")
    if agent.get("status") != "ok":
        raise ProbeUnavailable("Agent runtime reliability unavailable")

    model = health.get("loaded_model")
    if model is not None and (not isinstance(model, str) or not model):
        raise ProbeUnavailable("Invalid loaded_model")
    if server.get("loaded_model") != model:
        raise ProbeUnavailable("Model changed during inspection")
    loaded_models = server.get("loaded_models")
    if loaded_models is not None:
        if not isinstance(loaded_models, (list, dict)):
            raise ProbeUnavailable("Invalid model inventory")
        if len(loaded_models) > 1:
            raise ProbeUnavailable("Multiple model weights resident")

    return Snapshot(
        model=model,
        requests_started=_number(summary.get("requests_started"), "requests_started"),
        in_flight=_number(summary.get("in_flight"), "in_flight"),
        queue_depth=_number(server.get("request_queue_depth"), "request_queue_depth"),
        agent_runs=_number(agent.get("active_agent_runs"), "active_agent_runs"),
        last_request_at=summary.get("last_request_at"),
    )


@dataclass
class IdleTracker:
    since: float | None = None
    signature: tuple | None = None

    def observe(self, sample: Snapshot | None, now: float) -> float:
        if sample is None or not sample.model or not sample.idle:
            self.since = None
            self.signature = None
            return 0.0
        if self.signature != sample.signature or self.since is None:
            self.signature = sample.signature
            self.since = now
        return max(0.0, now - self.since)


def _unload() -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"{HOST}:8000/unload", data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError("MLX-VLM /unload returned non-200")


@contextmanager
def _runtime_guard():
    import runtime_coordinator as coordinator
    # The shared lock serializes all coordinated Chat/Agent/Media calls.
    with coordinator.runtime_lease(workload="runtime", timeout=1):
        yield


def attempt_unload(expected: Snapshot) -> str:
    """A single guarded unload; never repeatedly force-evict after errors."""
    with _runtime_guard():
        first = probe()
        if not first.idle or first.signature != expected.signature:
            return "request_changed"
        time.sleep(0.2)
        second = probe()
        if not second.idle or second.signature != expected.signature:
            return "request_changed"
        _unload()
        health = _json_get(8000, "/health")
        return "unloaded" if health.get("loaded_model") is None else "unload_unverified"


def status_line(sample: Snapshot | None, age: float, action: str, *, apply: bool) -> str:
    return json.dumps({
        "action": action,
        "mode": "enabled" if apply else "observe_only",
        "model_loaded": bool(sample and sample.model),
        "in_flight": sample.in_flight if sample else None,
        "queue_depth": sample.queue_depth if sample else None,
        "agent_runs": sample.agent_runs if sample else None,
        "observed_idle_seconds": round(age, 1),
    }, separators=(",", ":"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only diagnostic")
    mode.add_argument("--watch", action="store_true", help="Poll continuously")
    parser.add_argument("--apply", action="store_true", help="Permit idle /unload (with --watch only)")
    parser.add_argument("--idle-seconds", type=int, default=DEFAULT_IDLE_SECONDS)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)
    if args.apply and not args.watch:
        parser.error("--apply requires --watch")
    if not 300 <= args.idle_seconds <= 86400 or not 5 <= args.poll_seconds <= 300:
        parser.error("Idle must be >=300s and poll interval 5..300s")
    if sys.platform != "darwin":
        parser.error("Only supported on macOS")

    tracker = IdleTracker()

    def read():
        try:
            return probe()
        except (OSError, ValueError, TimeoutError, ProbeUnavailable):
            # A failed probe resets the inactivity timer.
            return None

    if args.check:
        sample = read()
        print(status_line(sample, 0, "read_only", apply=False))
        return 0 if sample is not None else 2

    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while running:
        sample = read()
        age = tracker.observe(sample, time.monotonic())
        action = "unavailable" if sample is None else "observing"
        if sample is not None and age >= args.idle_seconds:
            if args.apply:
                try:
                    action = attempt_unload(sample)
                except Exception:
                    # Never retry automatically after an ambiguous failure.
                    action = "unload_failed"
                tracker.observe(None, time.monotonic())
            else:
                action = "eligible_dry_run"
        print(status_line(sample, age, action, apply=args.apply), flush=True)
        if running:
            time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
