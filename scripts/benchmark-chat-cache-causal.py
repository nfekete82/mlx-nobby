#!/usr/bin/env python3
"""Isolate prefill split effects from early cache snapshot storage on a Mac."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLX = ROOT / "scripts/mlx"
BENCH = ROOT / "scripts/benchmark-chat-cache.py"
FEATURE = "NOBBY_HYBRID_EARLY_CHECKPOINT"
STORE = "NOBBY_HYBRID_EARLY_CHECKPOINT_STORE"
DIAG = "NOBBY_HYBRID_CACHE_DIAG"
CASES = (("off", "0", "1"), ("split_only", "1", "0"), ("on", "1", "1"))


def launch_value(name):
    result = subprocess.run(["launchctl", "getenv", name],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def set_launch(name, value):
    if value == "":
        subprocess.run(["launchctl", "unsetenv", name], check=True)
    else:
        subprocess.run(["launchctl", "setenv", name, value], check=True)


def run_command(command):
    subprocess.run(command, cwd=ROOT, check=True)


def compare_case_rows(rows):
    if [r["mode"] for r in rows] != ["off", "split_only", "on"]:
        raise ValueError("Expected OFF, SPLIT_ONLY, ON in order")
    return {
        r["mode"]: {
            "first_turn_chars": r["turns"][0]["answer_chars"],
            "first_turn_exact_hits": r["turns"][0]["delta_exact_hits"],
            "third_turn_hits": r["turns"][2]["delta_exact_hits"],
            "third_turn_matched_tokens": r["turns"][2]["delta_matched_tokens"],
        } for r in rows
    }



def parse_lookup_diagnostic(entry):
    """Parse only numeric/boolean diagnostic metadata; never token contents."""
    if not isinstance(entry, str):
        return None
    wanted = ("reason", "prompt_tokens", "checkpoint_tokens",
              "matched_tokens", "common_prefix_tokens", "previous_tokens",
              "semantic_hash_same")
    parts = dict(re.findall(r"([a-z_]+)=([^\s]+)", entry))
    if not all(key in parts for key in wanted):
        return None
    try:
        result = {k: int(parts[k]) for k in wanted[1:-1]}
    except ValueError:
        return None
    result["reason"] = parts["reason"]
    result["semantic_hash_same"] = (
        True if parts["semantic_hash_same"] == "True"
        else False if parts["semantic_hash_same"] == "False" else None
    )
    return result


def prefix_gap_summary(rows):
    """Quantify why turn-3 exact lookup fails for identical replay histories.

    Estimated early boundaries are just numerical predictions, not proof
    that cache manager stored, retained or selected an early snapshot.
    """
    report = {}
    for row in rows:
        turns = row.get("turns") or []
        if len(turns) != 3:
            report[row.get("mode", "unknown")] = {"available": False}
            continue
        previous = parse_lookup_diagnostic(turns[1].get("hybrid_diagnostic"))
        current = parse_lookup_diagnostic(turns[2].get("hybrid_diagnostic"))
        if previous is None or current is None:
            report[row["mode"]] = {"available": False}
            continue
        checkpoint = previous["checkpoint_tokens"]
        prefix = current["common_prefix_tokens"]
        estimated_early = max(0, checkpoint - 160)
        report[row["mode"]] = {
            "available": True,
            "previous_full_checkpoint_tokens": checkpoint,
            "turn3_common_prefix_tokens": prefix,
            "turn3_prefix_gap_tokens": max(0, checkpoint - prefix),
            "turn3_semantic_hash_same": current["semantic_hash_same"],
            "turn3_reason": current["reason"],
            "turn3_actual_matched_tokens": current["matched_tokens"],
            "hypothetical_early_boundary_tokens": estimated_early,
            "hypothetical_early_within_common_prefix": (
                current["semantic_hash_same"] is True
                and estimated_early > 0
                and prefix >= estimated_early
            ),
        }
    return report


def compare_answers(rows):
    if not all("answers_file" in row for row in rows):
        return None
    answers = {}
    for r in rows:
        data = json.loads(Path(r["answers_file"]).read_text(encoding="utf-8"))
        if len(data["answers"]) != 3:
            raise ValueError("Missing captured answers")
        answers[r["mode"]] = data["answers"]
    result = {}
    for mode in ("split_only", "on"):
        ref = answers["off"]
        candidate = answers[mode]
        if any(a["question"] != b["question"] or a["turn"] != b["turn"]
               for a, b in zip(ref, candidate)):
            raise ValueError("Captured questions do not match")
        first_a, first_b = ref[0]["answer"], candidate[0]["answer"]
        result[f"off_vs_{mode}"] = {
            "first_turn_exact_equal": first_a == first_b,
            "first_turn_similarity": round(
                difflib.SequenceMatcher(None, first_a, first_b).ratio(), 3
            ),
        }
    a = answers["split_only"][0]["answer"]
    b = answers["on"][0]["answer"]
    result["split_only_vs_on"] = {
        "first_turn_exact_equal": a == b,
        "first_turn_similarity": round(difflib.SequenceMatcher(None, a, b).ratio(), 3),
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-restarts", action="store_true")
    parser.add_argument("--diagnose", action="store_true", help="Enable temporary numeric-only hybrid cache lookup diagnostics")
    parser.add_argument("--fixed-history", action="store_true",
                        help="Replay the OFF run's assistant replies when testing SPLIT_ONLY and ON")
    parser.add_argument("--capture-answers", action="store_true",
                        help="Opt-in: save full generated answers locally (0600 files)")
    parser.add_argument("--output", default="/tmp/chat-cache-causal-report.json")
    parser.add_argument("--settle-seconds", type=float, default=3)
    args = parser.parse_args(argv)
    if not args.confirm_restarts:
        parser.error("This experiment restarts MLX four times; pass --confirm-restarts")
    if args.fixed_history and not args.capture_answers:
        parser.error("--fixed-history requires --capture-answers for its OFF baseline")
    report_file = Path(args.output)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    capture_dir = report_file.with_name(report_file.stem + "-answers")
    if args.capture_answers:
        if capture_dir.is_symlink():
            parser.error("Refusing symlinked capture directory")
        capture_dir.mkdir(mode=0o700, exist_ok=True)
        capture_dir.chmod(0o700)
        print("Raw output files (private):", capture_dir, flush=True)
    flag_names = (FEATURE, STORE, DIAG) if args.diagnose else (FEATURE, STORE)
    initial = {name: launch_value(name) for name in flag_names}
    if any(value not in ("", "0", "1") for value in initial.values()):
        parser.error("Unexpected launchctl early-checkpoint configuration")
    rows = []
    try:
        for mode, feature, store in CASES:
            print(f"\n=== Causal test: {mode} ===", flush=True)
            set_launch(FEATURE, feature)
            set_launch(STORE, store)
            if args.diagnose:
                set_launch(DIAG, "1")
            run_command([str(MLX), "restart"])
            time.sleep(args.settle_seconds)
            output = report_file.with_name(report_file.stem + f"-{mode}.json")
            cmd = [sys.executable, str(BENCH), "--temperature", "0",
                   "--json-out", str(output)]
            captured = capture_dir / (mode + ".json")
            if args.capture_answers:
                cmd += ["--answers-out", str(captured)]
            if args.diagnose:
                cmd += ["--diagnose"]
            if args.fixed_history and mode != "off":
                cmd += ["--replay-answers", str(capture_dir / "off.json")]
            run_command(cmd)
            row = json.loads(output.read_text(encoding="utf-8"))
            row["mode"] = mode
            row["history_mode"] = "baseline_replay" if args.fixed_history and mode != "off" else "generated"
            if args.capture_answers:
                row["answers_file"] = str(captured)
            rows.append(row)
            print(f"{mode}: first chars={row['turns'][0]['answer_chars']}, "
                  f"turn3 matched={row['turns'][2]['delta_matched_tokens']}", flush=True)
        summary = compare_case_rows(rows)
        comparison = compare_answers(rows)
        report = {
            "design": "OFF vs split-only vs ON, model restart for each",
            "fixed_history": args.fixed_history,
            "note": ("All three modes use the OFF run's assistant history for subsequent requests. "
                     "Outputs may still differ; cache-hit differences do not prove semantic correctness."
                     if args.fixed_history else
                     "Each run uses its own generated assistant history, so input prompts diverge after turn 1. "
                     "Textual similarity is not semantic equivalence."),
            "summary": summary,
            "comparison": comparison,
            "quality_review": "PENDING",
            "prefix_gap_diagnostics": prefix_gap_summary(rows) if args.diagnose else None,
            "runs": rows,
        }
        report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("\nCausal summary:\n" + json.dumps(summary, indent=2), flush=True)
        if comparison is not None:
            print("First-turn text comparison:\n" + json.dumps(comparison, indent=2), flush=True)
        if args.diagnose:
            print("Prefix gap diagnostics:\n" + json.dumps(report["prefix_gap_diagnostics"], indent=2), flush=True)
        print("Report:", report_file, flush=True)
        return 0
    finally:
        for name, value in initial.items():
            try:
                set_launch(name, value)
            except subprocess.CalledProcessError as error:
                print(f"RESTORE FAILED for {name}: {error}", file=sys.stderr, flush=True)
        try:
            run_command([str(MLX), "restart"])
        except subprocess.CalledProcessError as error:
            print(f"RESTORE RESTART FAILED: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
