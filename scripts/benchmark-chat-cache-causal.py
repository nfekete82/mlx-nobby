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
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLX = ROOT / "scripts/mlx"
BENCH = ROOT / "scripts/benchmark-chat-cache.py"
FEATURE = "NOBBY_HYBRID_EARLY_CHECKPOINT"
STORE = "NOBBY_HYBRID_EARLY_CHECKPOINT_STORE"
DIAG = "NOBBY_HYBRID_CACHE_DIAG"
SLOTS = "NOBBY_HYBRID_EXACT_CACHE_ENTRIES"
ALIGN = "NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE"
SLOT_CASES = (
    ("baseline1", "0", "1", "1"),
    ("baseline2", "0", "1", "2"),
    ("split2", "1", "0", "2"),
    ("early2", "1", "1", "2"),
)
NATIVE_CASES = (
    ("baseline1", "0", "1", "1", "0"),
    ("baseline2", "0", "1", "2", "0"),
    ("early2", "1", "1", "2", "0"),
    ("native2", "1", "1", "2", "1"),
)
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


def memory_snapshot():
    """Optional agent telemetry; not a direct snapshot memory measurement."""
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/api/performance/observatory?limit=1", timeout=5
        ) as response:
            payload = json.load(response)
        memory = (payload.get("system") or {}).get("memory") or {}
        return {key: memory.get(key) for key in (
            "swap_used_gb", "headroom_gb", "free_percent", "pressure"
        )}
    except (OSError, ValueError, TypeError):
        return {"unavailable": True}


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



def compare_slot_rows(rows):
    if [row["mode"] for row in rows] != [case[0] for case in SLOT_CASES]:
        raise ValueError("Expected baseline1, baseline2, split2, early2 in order")
    return {
        row["mode"]: {
            "slots": row["exact_cache_slots"],
            "first_turn_chars": row["turns"][0]["answer_chars"],
            "first_turn_hits": row["turns"][0]["delta_exact_hits"],
            "turn2_matched_tokens": row["turns"][1]["delta_matched_tokens"],
            "turn3_hits": row["turns"][2]["delta_exact_hits"],
            "turn3_matched_tokens": row["turns"][2]["delta_matched_tokens"],
            "turn3_first_content_ms": row["turns"][2]["first_content_ms"],
            "total_stores": sum(turn["delta_exact_stores"] for turn in row["turns"]),
        } for row in rows
    }


def compare_native_rows(rows):
    """Report the same fixed-history statistics for native chunk boundaries."""
    expected = [case[0] for case in NATIVE_CASES]
    if [row["mode"] for row in rows] != expected:
        raise ValueError("Expected baseline1, baseline2, early2, native2")
    return {row["mode"]: {
        "slots": row["exact_cache_slots"],
        "first_turn_chars": row["turns"][0]["answer_chars"],
        "first_turn_hits": row["turns"][0]["delta_exact_hits"],
        "turn2_matched_tokens": row["turns"][1]["delta_matched_tokens"],
        "turn3_hits": row["turns"][2]["delta_exact_hits"],
        "turn3_matched_tokens": row["turns"][2]["delta_matched_tokens"],
        "turn3_first_content_ms": row["turns"][2]["first_content_ms"],
        "turn3_total_ms": row["turns"][2]["total_ms"],
        "total_stores": sum(turn["delta_exact_stores"] for turn in row["turns"]),
    } for row in rows}


def compare_native_answers(rows):
    answers = {}
    for row in rows:
        with open(row["answers_file"], encoding="utf-8") as stream:
            data = json.load(stream)
        entries = data.get("answers")
        if not isinstance(entries, list) or len(entries) != 3:
            raise ValueError("Expected three captured answers per variant")
        answers[row["mode"]] = entries
    ref = answers["baseline1"]
    comparisons = {}
    for mode in ("baseline2", "early2", "native2"):
        candidate = answers[mode]
        if any(a["question"] != b["question"] or a["turn"] != b["turn"]
               for a, b in zip(ref, candidate)):
            raise ValueError("Questions mismatch across native-boundary variants")
        comparisons["baseline1_vs_" + mode] = {
            "turn1_exact_equal": ref[0]["answer"] == candidate[0]["answer"],
            "turn1_similarity": round(difflib.SequenceMatcher(
                None, ref[0]["answer"], candidate[0]["answer"]
            ).ratio(), 3),
        }
    comparisons["early2_vs_native2"] = {
        "turn1_exact_equal": (
            answers["early2"][0]["answer"] == answers["native2"][0]["answer"]
        ),
    }
    return comparisons


def compare_slot_answers(rows):
    by_mode = {}
    for row in rows:
        with open(row["answers_file"], encoding="utf-8") as handle:
            data = json.load(handle)
        answer_rows = data["answers"]
        if len(answer_rows) != 3:
            raise ValueError("Need three answers for each variant")
        by_mode[row["mode"]] = answer_rows
    results = {}
    for mode in ("baseline2", "split2", "early2"):
        before, after = by_mode["baseline1"], by_mode[mode]
        if any(a["question"] != b["question"] or a["turn"] != b["turn"]
               for a, b in zip(before, after)):
            raise ValueError("Questions mismatch across slots variants")
        results["baseline1_vs_" + mode] = {
            "turn1_exact_equal": before[0]["answer"] == after[0]["answer"],
            "turn1_similarity": round(difflib.SequenceMatcher(
                None, before[0]["answer"], after[0]["answer"]
            ).ratio(), 3),
        }
    results["split2_vs_early2"] = {
        "turn1_exact_equal": (
            by_mode["split2"][0]["answer"] == by_mode["early2"][0]["answer"]
        ),
    }
    return results


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
    parser.add_argument("--compare-native", action="store_true",
                        help="Compare same-history forced early split versus native-chunk-aligned snapshot")
    parser.add_argument("--compare-slots", action="store_true",
                        help="Run four fixed-history cases comparing exact APC LRU capacity 1 vs 2")
    parser.add_argument("--diagnose", action="store_true", help="Enable temporary numeric-only hybrid cache lookup diagnostics")
    parser.add_argument("--fixed-history", action="store_true",
                        help="Replay the OFF run's assistant replies when testing SPLIT_ONLY and ON")
    parser.add_argument("--capture-answers", action="store_true",
                        help="Opt-in: save full generated answers locally (0600 files)")
    parser.add_argument("--output", default="/tmp/chat-cache-causal-report.json")
    parser.add_argument("--settle-seconds", type=float, default=3)
    args = parser.parse_args(argv)
    if not args.confirm_restarts:
        parser.error("This experiment restarts MLX four times (five with --compare-slots or --compare-native); pass --confirm-restarts")
    if args.fixed_history and not args.capture_answers:
        parser.error("--fixed-history requires --capture-answers for its OFF baseline")
    if args.compare_native and args.compare_slots:
        parser.error("--compare-native and --compare-slots are mutually exclusive")
    if args.compare_native and not (args.fixed_history and args.capture_answers and args.diagnose):
        parser.error("--compare-native requires --fixed-history --capture-answers --diagnose")
    if args.compare_slots and not (args.fixed_history and args.capture_answers and args.diagnose):
        parser.error("--compare-slots requires --fixed-history --capture-answers --diagnose")
    report_file = Path(args.output)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    capture_dir = report_file.with_name(report_file.stem + "-answers")
    if args.capture_answers:
        if capture_dir.is_symlink():
            parser.error("Refusing symlinked capture directory")
        capture_dir.mkdir(mode=0o700, exist_ok=True)
        capture_dir.chmod(0o700)
        print("Raw output files (private):", capture_dir, flush=True)
    flag_names = (
        (FEATURE, STORE, DIAG, SLOTS, ALIGN) if (args.compare_native or args.compare_slots)
        else (FEATURE, STORE, DIAG, ALIGN) if args.diagnose
        else (FEATURE, STORE, ALIGN)
    )
    initial = {name: launch_value(name) for name in flag_names}
    if any(initial[name] not in ("", "0", "1") for name in initial if name != SLOTS):
        parser.error("Unexpected launchctl early-checkpoint configuration")
    if ALIGN in initial and initial[ALIGN] not in ("", "0", "1"):
        parser.error("Unexpected existing native-alignment configuration")
    if SLOTS in initial and initial[SLOTS] not in ("", "1", "2"):
        parser.error("Unexpected existing exact cache capacity (must be 1 or 2)")
    rows = []
    try:
        cases = (
            NATIVE_CASES if args.compare_native
            else tuple((mode, feature, store, slots, "0")
                       for mode, feature, store, slots in SLOT_CASES)
            if args.compare_slots
            else tuple((mode, feature, store, None, "0")
                       for mode, feature, store in CASES)
        )
        for mode, feature, store, slots, align in cases:
            print(f"\n=== Causal test: {mode} ===", flush=True)
            set_launch(FEATURE, feature)
            set_launch(STORE, store)
            if slots is not None:
                set_launch(SLOTS, slots)
            if align is not None:
                set_launch(ALIGN, align)
            if args.diagnose:
                set_launch(DIAG, "1")
            run_command([str(MLX), "restart"])
            time.sleep(args.settle_seconds)
            output = report_file.with_name(report_file.stem + f"-{mode}.json")
            before_memory = memory_snapshot() if (args.compare_slots or args.compare_native) else None
            cmd = [sys.executable, str(BENCH), "--temperature", "0",
                   "--json-out", str(output)]
            captured = capture_dir / (mode + ".json")
            if args.capture_answers:
                cmd += ["--answers-out", str(captured)]
            if args.diagnose:
                cmd += ["--diagnose"]
            baseline = "baseline1" if (args.compare_slots or args.compare_native) else "off"
            if args.fixed_history and mode != baseline:
                cmd += ["--replay-answers", str(capture_dir / (baseline + ".json"))]
            run_command(cmd)
            row = json.loads(output.read_text(encoding="utf-8"))
            row["mode"] = mode
            if args.compare_slots or args.compare_native:
                row["memory_before"] = before_memory
                row["memory_after"] = memory_snapshot()
            if slots is not None:
                row["exact_cache_slots"] = int(slots)
            row["history_mode"] = "baseline_replay" if args.fixed_history and mode != baseline else "generated"
            if args.capture_answers:
                row["answers_file"] = str(captured)
            rows.append(row)
            print(f"{mode}: first chars={row['turns'][0]['answer_chars']}, "
                  f"turn3 matched={row['turns'][2]['delta_matched_tokens']}", flush=True)
        summary = (compare_native_rows(rows) if args.compare_native
                   else compare_slot_rows(rows) if args.compare_slots
                   else compare_case_rows(rows))
        comparison = (compare_native_answers(rows) if args.compare_native
                      else compare_slot_answers(rows) if args.compare_slots
                      else compare_answers(rows))
        report = {
            "design": (
                "1-slot and 2-slot baseline vs forced and native-boundary early checkpoints"
                if args.compare_native else
                "1-slot baseline vs 2-slot baseline/split-only/early checkpoint"
                if args.compare_slots else "OFF vs split-only vs ON, model restart for each"
            ),
            "slot_control": args.compare_slots or args.compare_native,
            "native_boundary_control": args.compare_native,
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
