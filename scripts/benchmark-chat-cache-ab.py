#!/usr/bin/env python3
"""Compare OFF/ON early checkpoint with alternating, restarted model-server runs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request
import difflib
import runpy
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "scripts/benchmark-chat-cache.py"


def evaluate_release_gates(report):
    return runpy.run_path(str(ROOT / "scripts/checkpoint_release_gates.py"))["evaluate"](report)
MLX = ROOT / "scripts/mlx"


def run_checked(command, env=None):
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def summarize(reports):
    grouped = {"off": [], "on": []}
    for report in reports:
        grouped[report["mode"]].append(report)
    result = {}
    for mode, runs in grouped.items():
        turns = [run["turns"][2] for run in runs]
        result[mode] = {
            "runs": len(runs),
            "turn3_exact_hits": [t["delta_exact_hits"] for t in turns],
            "turn3_matched_tokens": [t["delta_matched_tokens"] for t in turns],
            "turn3_first_content_ms_median": statistics.median(t["first_content_ms"] for t in turns),
            "turn3_total_ms_median": statistics.median(t["total_ms"] for t in turns),
        }
    return result


def memory_snapshot(agent_url: str = "http://127.0.0.1:8010"):
    try:
        with urllib.request.urlopen(agent_url + "/api/performance/observatory?limit=1", timeout=10) as response:
            data = json.load(response)
        memory = ((data.get("system") or {}).get("memory") or {})
        return {key: memory.get(key) for key in
                ("swap_used_gb", "headroom_gb", "free_percent", "pressure")}
    except (OSError, ValueError):
        return {"unavailable": True}


def swap_difference(before, after):
    a = before.get("swap_used_gb")
    b = after.get("swap_used_gb")
    return round(b - a, 3) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None


def compare_captured_answers(reports):
    """Exact and textual comparison only; never certify semantic correctness."""
    comparisons = []
    for index in range(0, len(reports) - 1, 2):
        off, on = reports[index:index + 2]
        if off.get("mode") != "off" or on.get("mode") != "on":
            raise ValueError("Expected alternating OFF/ON response captures")
        before = json.loads(Path(off["answers_file"]).read_text(encoding="utf-8"))["answers"]
        after = json.loads(Path(on["answers_file"]).read_text(encoding="utf-8"))["answers"]
        if len(before) != 3 or len(after) != 3:
            raise ValueError("All three turn answers must be present")
        turns = []
        for b, a in zip(before, after):
            if b["question"] != a["question"] or b["turn"] != a["turn"]:
                raise ValueError("Question or turn changed between OFF and ON")
            bt, at = b["answer"], a["answer"]
            turns.append({"turn": b["turn"], "exact_equal": bt == at,
                          "off_chars": len(bt), "on_chars": len(at),
                          "similarity": round(difflib.SequenceMatcher(None, bt, at).ratio(), 3)})
        comparisons.append({"pair": index // 2 + 1, "turns": turns})
    return comparisons


def sequence(pairs):
    return ["off", "on"] * pairs


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", type=int, default=2)
    p.add_argument("--output", default="/tmp/chat-cache-ab-report.json")
    p.add_argument("--web-url", default="http://127.0.0.1:8090")
    p.add_argument("--server-url", default="http://127.0.0.1:8000")
    p.add_argument("--max-tokens", type=int, default=700)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--settle-seconds", type=int, default=3)
    p.add_argument("--confirm-restarts", action="store_true")
    p.add_argument("--quality-review", action="store_true", help="Mark response quality as pending manual review")
    p.add_argument("--capture-answers", action="store_true",
                   help="OPT-IN: save raw model answers to private JSON files for manual comparison")
    p.add_argument("--release-gates", action="store_true", help="Evaluate conservative soak readiness (requires >=3 OFF and >=3 ON runs)")
    args = p.parse_args(argv)
    if args.pairs < 1 or args.pairs > 5:
        p.error("--pairs must be between 1 and 5")
    if args.capture_answers and not args.quality_review:
        p.error("--capture-answers requires --quality-review")
    if not args.confirm_restarts:
        p.error("This test restarts the MLX server before each run. Pass --confirm-restarts.")
    # Share the controlled runner: freeze ALL experiment flags, verify the
    # live profile and restore even originally unset launchctl values.
    spec = importlib.util.spec_from_file_location(
        "nobby_causal_benchmark", ROOT / "scripts/benchmark-chat-cache-causal.py"
    )
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    profile = runpy.run_path(str(ROOT / "scripts/chat-performance-profile.py"))
    profile["ensure_idle"]()
    profile["confirm_profile"]("hybrid")
    controlled = (control.FEATURE, control.STORE, control.ALIGN, control.SLOTS)
    initial = {name: control.launch_value(name) for name in controlled}
    if any(value not in ("", "0", "1") for name, value in initial.items()
           if name != control.SLOTS) or initial[control.SLOTS] not in ("", "1", "2"):
        p.error("Unexpected existing launchctl experiment settings")
    before = subprocess.run(["launchctl", "getenv", "NOBBY_HYBRID_EARLY_CHECKPOINT"],
                            capture_output=True, text=True, check=False).stdout.strip()
    if before not in {"", "0", "1"}:
        p.error("Unexpected existing launchctl checkpoint setting; refusing to override.")
    results = []
    report_path = Path(args.output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    answers_dir = report_path.with_name(report_path.stem + "-answers")
    if args.capture_answers:
        if answers_dir.is_symlink():
            p.error("Refusing symlinked answers directory")
        answers_dir.mkdir(mode=0o700, exist_ok=True)
        answers_dir.chmod(0o700)
        print("PRIVACY: saving raw answer text under", answers_dir, flush=True)
    try:
        for i, mode in enumerate(sequence(args.pairs), 1):
            print(f"\n=== A/B run {i}: early checkpoint {mode.upper()} ===", flush=True)
            run_checked(["launchctl", "setenv", "NOBBY_HYBRID_EARLY_CHECKPOINT",
                         "1" if mode == "on" else "0"])
            control.set_launch(control.STORE, "1")
            control.set_launch(control.ALIGN, "0")
            control.set_launch(control.SLOTS, "2")
            run_checked([str(MLX), "restart"])
            time.sleep(args.settle_seconds)
            profile["confirm_profile"]("hybrid")
            turn_path = report_path.with_suffix(f".run{i}.json")
            before_memory = memory_snapshot()
            command = [sys.executable, str(BENCH), "--web-url", args.web_url,
                       "--server-url", args.server_url, "--max-tokens",
                       str(args.max_tokens), "--timeout", str(args.timeout),
                       "--temperature", "0", "--json-out", str(turn_path)]
            answers_file = answers_dir / f"run{i}-{mode}.json"
            if args.capture_answers:
                command.extend(["--answers-out", str(answers_file)])
                if mode == "on":
                    command.extend(["--replay-answers", results[-1]["answers_file"]])
            run_checked(command)
            record = json.loads(turn_path.read_text(encoding="utf-8"))
            record["mode"] = mode
            if args.capture_answers:
                record["answers_file"] = str(answers_file)
            record["memory_after_run"] = memory_snapshot()
            record["memory_before_run"] = before_memory
            record["memory_delta_swap_gb"] = swap_difference(before_memory, record["memory_after_run"])
            results.append(record)
            print(f"Run {i} turn3: {record['turns'][2]['delta_matched_tokens']} cached tokens", flush=True)
        final = {"design": "alternating OFF/ON, fresh server restart each run",
                 "caveats": "Model outputs and RAG may differ. Global cache counters require no concurrent traffic.",
                 "summary": summarize(results), "runs": results}
        if args.release_gates:
            final["release_gates"] = evaluate_release_gates(final)
        if args.quality_review:
            final["quality_review"] = {"status": "PENDING", "note": "Manual semantic comparison required; identical text is not required, and similarity scores cannot establish correctness."}
            if args.capture_answers:
                comparisons = compare_captured_answers(results)
                final["quality_review"]["text_comparisons"] = comparisons
                if any(not pair["turns"][0]["exact_equal"] for pair in comparisons):
                    final["quality_review"]["first_turn_divergence"] = True
                    final["quality_review"]["warning"] = "OFF/ON differ even at turn 1 (before any cache hit). Inspect responses and prefill chunking before merging."
        report_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
        print("\nA/B summary:\n", json.dumps(final["summary"], indent=2), flush=True)
        if args.release_gates:
            print("Release gates:", json.dumps(final["release_gates"], indent=2), flush=True)
        if args.capture_answers:
            print("Quality review: PENDING (read raw answers in", answers_dir, ")", flush=True)
            if final["quality_review"].get("first_turn_divergence"):
                print("CAUTION: first-turn output differs with checkpoint ON vs OFF; manual inspection required", flush=True)
        print("Report:", report_path)
        return 0
    finally:
        # Do not leave experiment enabled after any error or interruption.
        restore_errors = []
        for name, value in initial.items():
            try:
                control.set_launch(name, value)
            except subprocess.CalledProcessError as error:
                restore_errors.append(str(error))
        try:
            run_checked([str(MLX), "restart"])
        except subprocess.CalledProcessError as error:
            restore_errors.append(str(error))
        if restore_errors:
            raise RuntimeError("Benchmark restoration failed: " + "; ".join(restore_errors))


if __name__ == "__main__":
    raise SystemExit(main())
