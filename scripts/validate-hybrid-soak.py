#!/usr/bin/env python3
"""Opt-in repeated Apple Silicon hybrid quality soak with safe profile restoration.

No real prompts, generated text or conversations are written to disk.
Unlike a continuously running benchmark, this is a bounded repeatability gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import signal
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Missing {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load("soak_quality", "validate-hybrid-longform.py")
profile = quality.profile


def order_for_round(index: int) -> tuple[str, str]:
    # Counterbalance restart/order bias across successive rounds.
    return ("dflash", "hybrid") if index % 2 == 0 else ("hybrid", "dflash")


def summarize(result: dict) -> dict:
    return {
        "profile": result["profile"],
        "passed": result["passed"],
        "checks": result["checks"],
        "synthetic_marker_diagnostics": result["synthetic_marker_diagnostics"],
        "followup_first_content_ms": result["followup_first_content_ms"],
        "followup_total_ms": result["followup_total_ms"],
        "followup_output_characters": result["followup_output_characters"],
        "memory_before": result["memory_before"],
        "memory_after": result["memory_after"],
        "swap_delta_gb": result["swap_delta_gb"],
        "exact_hits_before": result["exact_hits_before"],
        "exact_hits_after": result["exact_hits_after"],
    }


def sample_during_workload(work, interval_seconds: float = 2.0):
    """Sample memory while a synchronous inference workload executes."""
    done = threading.Event()
    samples = []
    errors = []

    def poll():
        while not done.is_set():
            try:
                samples.append(profile.memory_snapshot())
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(type(exc).__name__)
                break
            done.wait(interval_seconds)

    monitor = threading.Thread(target=poll, name="hybrid-memory-monitor", daemon=True)
    monitor.start()
    try:
        result = work()
    finally:
        done.set()
        monitor.join(timeout=15)
    if monitor.is_alive() or errors or not samples:
        raise RuntimeError("Memory sampling failed; cannot approve workload")
    headrooms = [s.get("headroom_gb") for s in samples]
    swaps = [s.get("swap_used_gb") for s in samples]
    if any(type(v) not in (int, float) for v in headrooms + swaps):
        raise RuntimeError("Invalid memory sample")
    summary = {
        "sample_count": len(samples),
        "minimum_headroom_gb": round(min(headrooms), 3),
        "maximum_swap_used_gb": round(max(swaps), 3),
        "sampled_swap_growth_gb": round(max(swaps) - swaps[0], 3),
        "all_pressure_normal": all(s.get("pressure") == "normal" for s in samples),
        "sampling_interval_seconds": interval_seconds,
    }
    if summary["minimum_headroom_gb"] < 5 or summary["sampled_swap_growth_gb"] > 1 or not summary["all_pressure_normal"]:
        raise RuntimeError("Sampled memory safety gate failed")
    return result, summary


def run(rounds: int, contexts: tuple[int, ...], timeout: int) -> dict:
    profile.ensure_idle()
    initial = profile.configured_profile(profile.CONFIG.read_text(encoding="utf-8"))
    if initial != "default":
        raise RuntimeError("Start in default profile; no changes made")
    if not profile.current_server_args():
        raise RuntimeError("No local MLX-VLM model server")
    profile.preflight("dflash")
    handlers = {}

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    for signum in (signal.SIGINT, signal.SIGTERM):
        handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt)

    rows = []
    started = time.monotonic()
    try:
        for index in range(rounds):
            for context_size in contexts:
                for mode in order_for_round(index):
                    profile.ensure_idle()
                    profile.switch_profile(mode)
                    (result, _), sampled = sample_during_workload(
                        lambda: quality.run_mode(mode, context_size, 400, timeout)
                    )
                    row = summarize(result)
                    row["sampled_memory"] = sampled
                    row["round"] = index + 1
                    row["nominal_context_tokens"] = context_size
                    rows.append(row)
                    print(
                        f"round={index+1} context={context_size} mode={mode} "
                        f"passed={result['passed']} total_ms={result['followup_total_ms']:.1f}",
                        file=sys.stderr, flush=True,
                    )
                    if not result["passed"]:
                        raise RuntimeError("Quality gate failed; stopping without further inference")
    finally:
        try:
            current = profile.configured_profile(profile.CONFIG.read_text(encoding="utf-8"))
            if current != initial:
                profile.switch_profile(initial)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    return {
        "schema": 1,
        "kind": "hybrid_repeatability_soak",
        "passed": bool(rows) and all(row["passed"] for row in rows),
        "starting_profile_restored": initial,
        "rounds": rounds,
        "nominal_context_sizes": list(contexts),
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "results": rows,
        "notes": [
            "All workloads are synthetic and generated text is not persisted.",
            "Order alternates between rounds; this is not randomized or blinded.",
            "Two-second memory samples may still miss transient peaks.",
            "This is a bounded smoke/soak, not proof of output equivalence or multi-hour media stability.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--context-sizes", default="4000,8000")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 12:
        parser.error("rounds must be within 1..12")
    if not 30 <= args.timeout <= 600:
        parser.error("timeout must be within 30..600")
    try:
        contexts = tuple(int(value.strip()) for value in args.context_sizes.split(","))
    except ValueError:
        parser.error("context sizes must be comma-separated integers")
    if not contexts or len(set(contexts)) != len(contexts) or any(x not in (4000, 8000) for x in contexts):
        parser.error("context sizes must be unique values from 4000,8000")
    try:
        report = run(args.rounds, contexts, args.timeout)
        data = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            # Fail closed if the target already exists; never overwrite a prior run.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(data + "\n")
            args.output.chmod(0o600)
        print(data)
        return 0 if report["passed"] else 2
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"Hybrid soak stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
