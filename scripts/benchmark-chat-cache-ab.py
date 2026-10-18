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

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "scripts/benchmark-chat-cache.py"
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
    args = p.parse_args(argv)
    if args.pairs < 1 or args.pairs > 5:
        p.error("--pairs must be between 1 and 5")
    if not args.confirm_restarts:
        p.error("This test restarts the MLX server before each run. Pass --confirm-restarts.")
    before = subprocess.run(["launchctl", "getenv", "NOBBY_HYBRID_EARLY_CHECKPOINT"],
                            capture_output=True, text=True, check=False).stdout.strip()
    if before not in {"", "0", "1"}:
        p.error("Unexpected existing launchctl checkpoint setting; refusing to override.")
    results = []
    report_path = Path(args.output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        for i, mode in enumerate(sequence(args.pairs), 1):
            print(f"\n=== A/B run {i}: early checkpoint {mode.upper()} ===", flush=True)
            run_checked(["launchctl", "setenv", "NOBBY_HYBRID_EARLY_CHECKPOINT",
                         "1" if mode == "on" else "0"])
            run_checked([str(MLX), "restart"])
            time.sleep(args.settle_seconds)
            turn_path = report_path.with_suffix(f".run{i}.json")
            run_checked([sys.executable, str(BENCH), "--web-url", args.web_url,
                         "--server-url", args.server_url, "--max-tokens",
                         str(args.max_tokens), "--timeout", str(args.timeout),
                         "--temperature", "0", "--json-out", str(turn_path)])
            record = json.loads(turn_path.read_text(encoding="utf-8"))
            record["mode"] = mode
            results.append(record)
            print(f"Run {i} turn3: {record['turns'][2]['delta_matched_tokens']} cached tokens", flush=True)
        final = {"design": "alternating OFF/ON, fresh server restart each run",
                 "caveats": "Model outputs and RAG may differ. Global cache counters require no concurrent traffic.",
                 "summary": summarize(results), "runs": results}
        report_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
        print("\nA/B summary:\n", json.dumps(final["summary"], indent=2), flush=True)
        print("Report:", report_path)
        return 0
    finally:
        # Do not leave experiment enabled after any error or interruption.
        subprocess.run(["launchctl", "setenv", "NOBBY_HYBRID_EARLY_CHECKPOINT", before or "0"],
                       check=False)
        subprocess.run([str(MLX), "restart"], cwd=ROOT, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
