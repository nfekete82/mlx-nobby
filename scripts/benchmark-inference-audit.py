#!/usr/bin/env python3
"""Bounded native/gateway SSE measurements on an already loaded, idle model.

No model switching, unload, cache reset, configuration writes or private output.
Run before and after activation with the same sample count and runtime settings.
"""

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_coordinator as coordinator

AGENT = "http://127.0.0.1:8010"
NATIVE = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:8090"
PROFILES = {
    "short": [{"role": "user", "content": "List numbers 1 through 24, separated by commas."}],
    "prefill": [
        {"role": "system", "content": "Ignore these inert calibration records.\n" +
         "record = alpha beta gamma delta epsilon.\n" * 128},
        {"role": "user", "content": "List numbers 1 through 24, separated by commas."},
    ],
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def get(client, origin, path):
    response = client.get(origin + path)
    response.raise_for_status()
    return response.json()


def preflight(client, model=None):
    agent = get(client, AGENT, "/api/runtime/reliability")
    queue = get(client, AGENT, "/api/system/job-queue?limit=1")
    lease = agent.get("lease") or {}
    if (agent.get("active_agent_runs") or lease.get("active_workload") or
            lease.get("waiting_count") or queue.get("active_count") or queue.get("waiting_count")):
        raise RuntimeError("Runtime is not idle; no benchmark request sent")
    for port in (8030, 8050, 8060):
        health = get(client, f"http://127.0.0.1:{port}", "/health")
        if health.get("active_generation") or health.get("active_job_id") or health.get("status") == "busy":
            raise RuntimeError("A native media workload is active")
    health = get(client, NATIVE, "/health")
    loaded = health.get("loaded_model")
    if not loaded or (model is not None and loaded != model):
        raise RuntimeError("Loaded model changed or is unavailable")
    memory = coordinator.memory_budget_snapshot()
    coordinator.ensure_active_memory_safe(memory)
    return loaded, health, memory


def measure(client, origin, model, messages, baseline_swap):
    memory_samples = []
    errors = []
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            try:
                memory = coordinator.memory_budget_snapshot()
                memory_samples.append(memory)
                coordinator.ensure_active_memory_safe(memory, baseline_swap_gb=baseline_swap)
            except Exception as exc:
                errors.append(type(exc).__name__)
                return
            stop.wait(1)

    payload = {"model": model, "messages": messages, "temperature": 0,
               "max_tokens": 96, "stream": True, "stream_options": {"include_usage": True}}
    if origin == NATIVE:
        payload["enable_thinking"] = False
    output = hashlib.sha256()
    timings, usage = {}, {}
    first = first_content = None
    finished = False
    started = time.perf_counter()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        with client.stream("POST", origin + "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                elapsed = time.perf_counter() - started
                if errors or elapsed > 30:
                    raise RuntimeError("Benchmark stopped by memory/deadline guard")
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    finished = True
                    break
                event = json.loads(raw)
                if event.get("error"):
                    raise RuntimeError("Native/gateway stream reported an error")
                for choice in event.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if content or reasoning:
                        if first is None:
                            first = elapsed * 1000
                        if content and first_content is None:
                            first_content = elapsed * 1000
                        output.update((reasoning + content).encode())
                timings.update(event.get("timings") or {})
                if event.get("usage"):
                    usage = event["usage"]
        wall = (time.perf_counter() - started) * 1000
        if not finished or first is None or errors:
            raise RuntimeError("Incomplete or unsafe benchmark stream")
    finally:
        stop.set()
        thread.join(timeout=12)
    return {
        "first_semantic_ms": round(first, 3),
        "first_content_ms": round(first_content, 3) if first_content is not None else None,
        "wall_ms": round(wall, 3), "timings": timings, "usage": usage,
        "output_sha256": output.hexdigest(), "input_sha256": fingerprint(payload),
        "free_percent_min": min((v["free_percent"] for v in memory_samples), default=None),
        "swap_peak_gb": max((v["swap_used_gb"] for v in memory_samples), default=None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--samples", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gateway", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new artifact path")
    report = {"phase": args.phase, "samples": [], "synthetic_workloads": True,
              "max_tokens": 96, "cache_reset": False, "model_switch": False}
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def save():
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(report, handle, indent=2)

    try:
        with httpx.Client(timeout=30, trust_env=False) as client:
            model, health, memory = preflight(client)
            settings = get(client, NATIVE, "/v1/settings")
            report.update(model_name=Path(model).name, model_sha256=fingerprint(model),
                          runtime_settings_fingerprint=settings.get("fingerprint"),
                          runtime_health={k: health.get(k) for k in (
                              "continuous_batching_enabled", "apc_enabled", "loaded_context_size",
                              "configured_context_limit", "effective_context_limit")},
                          memory_before=memory)
            for origin in ([NATIVE, WEB] if args.gateway else [NATIVE]):
                for profile, messages in PROFILES.items():
                    for index in range(args.samples + 1):
                        preflight(client, model)
                        # Gateway owns its own lease. Direct native requests use
                        # the same cross-service lease without nesting HTTP locks.
                        lease = coordinator.runtime_lease(workload="chat", timeout=1) if origin == NATIVE else nullcontext()
                        with lease:
                            sample = measure(client, origin, model if origin == NATIVE else "mlx-nobby/chat",
                                             messages, memory["swap_used_gb"])
                        sample.update(profile=profile, mode="native" if origin == NATIVE else "gateway",
                                      warmup=index == 0, index=index)
                        report["samples"].append(sample)
                        save()
                        print(json.dumps({k: sample[k] for k in (
                            "mode", "profile", "index", "first_semantic_ms", "wall_ms")}), flush=True)
            report["memory_after"] = coordinator.memory_budget_snapshot()
            report["complete"] = True
    except Exception as exc:
        report["complete"] = False
        report["error_type"] = type(exc).__name__
        save()
        raise
    report["summary"] = {}
    for mode in ("native", "gateway"):
        for profile in PROFILES:
            rows = [s for s in report["samples"] if s["mode"] == mode and s["profile"] == profile and not s["warmup"]]
            if rows:
                report["summary"][f"{mode}.{profile}"] = {
                    key: statistics.median(s[key] for s in rows)
                    for key in ("first_semantic_ms", "wall_ms")}
    save()
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
