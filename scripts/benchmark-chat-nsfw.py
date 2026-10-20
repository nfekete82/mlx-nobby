#!/usr/bin/env python3
"""Opt-in, LOCAL consenting-adult roleplay benchmark with human scoring only.

No auto model switch, no NSFW output in the metadata report, no automatic
"uncensored" quality claims. Reuses the guarded loopback-only Agent client.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nobby_chat_quality_client", ROOT / "scripts" / "benchmark-chat-quality.py"
)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)

SUITE = "mlx-nobby-chat-nsfw-v1"
SUITE_FILE = ROOT / "benchmarks" / "chat-nsfw-v1.json"
AXES = ("deutsch", "dialog", "stiltreue", "kontinuitaet", "grenzen")
MAX_RESPONSE_CHARS = client.MAX_ANSWER_CHARS


def suite() -> tuple[dict, str]:
    raw = SUITE_FILE.read_bytes()
    if len(raw) > 50_000:
        raise ValueError("Oversized roleplay suite")
    data = json.loads(raw)
    cases = data.get("cases")
    if (data.get("schema") != 1 or data.get("suite") != SUITE
            or not isinstance(cases, list) or len(cases) != 8
            or not isinstance(data.get("rubric"), dict)
            or set(data["rubric"]) != set(AXES)):
        raise ValueError("Unexpected roleplay suite")
    ids = set()
    for case in cases:
        ident = case.get("id")
        if (not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", ident)
                or ident in ids or case.get("kind") != "review"):
            raise ValueError("Invalid roleplay case")
        ids.add(ident)
        msgs = case.get("messages")
        checks = case.get("review_checks")
        if (not isinstance(msgs, list) or not msgs or msgs[-1].get("role") != "user"
                or any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                       or not isinstance(m.get("content"), str) or not m["content"]
                       or len(m["content"]) > 4000 for m in msgs)
                or not isinstance(checks, list) or not checks
                or any(not isinstance(c, str) or not c for c in checks)):
            raise ValueError("Invalid roleplay messages or review checks")
    return data, hashlib.sha256(raw).hexdigest()


def expected_model(model: str, expected: str) -> None:
    if not isinstance(model, str) or not model or expected.casefold() not in model.casefold():
        raise RuntimeError("EXPECTED_MODEL_MISMATCH")


def check_report(report: dict, cases: list[dict], fingerprint: str) -> None:
    if (report.get("schema") != 1 or report.get("suite") != SUITE
            or report.get("suite_sha256") != fingerprint
            or report.get("status") != "complete" or report.get("error_type") is not None
            or len(report.get("results", [])) != len(cases)):
        raise ValueError("Report must be a complete same-suite NSFW run")
    ids = [c["id"] for c in cases]
    if [r.get("id") for r in report["results"]] != ids:
        raise ValueError("Case order/IDs differ from frozen suite")
    for row in report["results"]:
        if row.get("grade") != "review_pending":
            raise ValueError("Invalid NSFW review status")
        for key in ("first_content_ms", "total_ms"):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid timing")
    if not isinstance(report.get("runtime"), dict) or not report["runtime"].get("model"):
        raise ValueError("Missing true model identity")


def run(origin: str, output: Path, review_file: Path, expected: str,
        max_tokens: int = 512, timeout: int = 180) -> dict:
    data, fingerprint = suite()
    client.fresh_paths([output, review_file])
    before = client.verify_status(client.get_json(origin, "/api/status"))
    expected_model(before["model"], expected)
    client.check_idle(client.get_json(origin, "/api/performance/observatory?limit=100"))
    cases = data["cases"]
    rows, reviews = [], []
    error_code = error_phase = error_type = None
    phase = "started"
    try:
        for index, case in enumerate(cases, 1):
            phase = "case_status:" + case["id"]
            client.verify_status(client.get_json(origin, "/api/status"), before)
            phase = "case_idle:" + case["id"]
            client.check_idle(client.get_json(origin, "/api/performance/observatory?limit=100"))
            phase = "case_stream:" + case["id"]
            timing, answer = client.agent_stream(origin, case["messages"], max_tokens, timeout)
            phase = "case_record:" + case["id"]
            if len(answer) > MAX_RESPONSE_CHARS:
                raise RuntimeError("Model response too long for benchmark")
            rows.append({"id": case["id"], "category": case["category"],
                         "grade": "review_pending", **timing})
            reviews.append({"id": case["id"], "messages": case["messages"],
                            "review_checks": case["review_checks"], "answer": answer})
            print(f"[{index}/{len(cases)}] {case['id']}: review_pending | "
                  f"TTFT {timing['first_content_ms']} ms", flush=True)
        phase = "final_status"
        client.verify_status(client.get_json(origin, "/api/status"), before)
        phase = "final_idle"
        client.check_idle(client.get_json(origin, "/api/performance/observatory?limit=100"))
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        error_type = type(exc).__name__
        error_code = ("EXPECTED_MODEL_MISMATCH" if
                      isinstance(exc, RuntimeError) and str(exc) == "EXPECTED_MODEL_MISMATCH"
                      else client.safe_error_code(exc))
        error_phase = phase
        print(f"NSFW benchmark aborted: {error_code} at {phase} (details withheld)", file=sys.stderr)
    complete = error_type is None and len(rows) == len(cases)

    def timing(name):
        values = [r[name] for r in rows]
        return round(statistics.median(values), 3) if values else None

    report = {
        "schema": 1, "suite": SUITE, "suite_sha256": fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if complete else "partial",
        "error_type": error_type, "error_code": error_code, "error_phase": error_phase,
        "runtime": before, "expected_model_query": expected,
        "parameters": {"temperature": 0, "max_tokens": max_tokens,
                       "auto_route": False, "transport": "agent_protected_stream"},
        "summary": {"review_pending": len(rows), "total": len(cases),
                    "p50_first_content_ms": timing("first_content_ms"),
                    "p50_total_ms": timing("total_ms"),
                    "automatic_quality_score": None},
        "results": rows,
        "limitations": [
            "Human judgment only; no automatic NSFW quality or censorship score.",
            "Only consenting fictional adult participants are included.",
            "Review answers remain local in the separate owner-only review file.",
            "Same hardware, temperature, prompt, generation settings and reviewer are recommended.",
            "A model name in a filename does not establish runtime identity.",
        ],
    }
    client.write_private(output, report)
    client.write_private(review_file, {
        "schema": 1, "suite": SUITE, "suite_sha256": fingerprint,
        "status": report["status"], "cases": reviews,
        "note": "Local sensitive synthetic prompts/completions. Do not commit/share this file.",
    })
    return report


def validate_scores(scores: dict, report: dict, cases: list[dict], fingerprint: str) -> dict:
    if (scores.get("schema") != 1 or scores.get("suite_sha256") != fingerprint
            or scores.get("model") != report["runtime"]["model"]):
        raise ValueError("Ratings do not match benchmark model/suite")
    rows = scores.get("scores")
    if not isinstance(rows, list) or [r.get("id") for r in rows] != [c["id"] for c in cases]:
        raise ValueError("Incomplete or unordered ratings")
    for row in rows:
        if set(row) != {"id", *AXES}:
            raise ValueError("Unexpected rating fields")
        if any(type(row[k]) is not int or not 1 <= row[k] <= 5 for k in AXES):
            raise ValueError("All human scores must be integers from 1 to 5")
    return scores


def score(report_path: Path, review_path: Path, output: Path) -> dict:
    data, fingerprint = suite()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    check_report(report, data["cases"], fingerprint)
    reviews = json.loads(review_path.read_text(encoding="utf-8"))
    if (reviews.get("suite_sha256") != fingerprint or reviews.get("status") != "complete"
            or [r.get("id") for r in reviews.get("cases", [])]
            != [c["id"] for c in data["cases"]]):
        raise ValueError("Wrong or incomplete local review file")
    client.fresh_paths([output])
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive scoring requires a terminal (TTY)")
    print("Private local human ratings; 1=schwach, 5=sehr gut; Ctrl-C aborts without saving.")
    print("Model identity:", report["runtime"]["model"])
    graded = []
    for i, (case, row) in enumerate(zip(data["cases"], reviews["cases"]), 1):
        print(f"\n=== {i}/{len(data['cases'])} — {case['id']} ===")
        print("Review criteria:")
        for criterion in case["review_checks"]:
            print(" -", criterion)
        print("\nModel output (local only):\n" + row["answer"][:MAX_RESPONSE_CHARS])
        values = {"id": case["id"]}
        for axis in AXES:
            while True:
                raw = input(f"{axis}: {data['rubric'][axis]} [1-5] > ").strip()
                if raw in ("1", "2", "3", "4", "5"):
                    values[axis] = int(raw)
                    break
                print("Please enter 1, 2, 3, 4 or 5.")
        graded.append(values)
    result = {"schema": 1, "suite_sha256": fingerprint,
              "model": report["runtime"]["model"], "scores": graded}
    client.write_private(output, result)
    return result


def compare(baseline: dict, candidate: dict, a: dict, b: dict) -> dict:
    data, fingerprint = suite()
    cases = data["cases"]
    check_report(baseline, cases, fingerprint)
    check_report(candidate, cases, fingerprint)
    model_a, model_b = baseline["runtime"]["model"], candidate["runtime"]["model"]
    if model_a == model_b:
        raise ValueError("Both reports are the SAME model, not an A/B model comparison")
    if baseline["parameters"] != candidate["parameters"]:
        raise ValueError("Different generation parameters")
    validate_scores(a, baseline, cases, fingerprint)
    validate_scores(b, candidate, cases, fingerprint)

    def means(scores):
        return {axis: round(statistics.mean(row[axis] for row in scores["scores"]), 3)
                for axis in AXES}

    avg_a, avg_b = means(a), means(b)
    total_a = round(statistics.mean(avg_a.values()), 3)
    total_b = round(statistics.mean(avg_b.values()), 3)
    return {
        "schema": 1, "suite": SUITE, "suite_sha256": fingerprint,
        "baseline_model": model_a, "candidate_model": model_b,
        "reviewed_cases": len(cases), "score_range": "1..5, human rated",
        "baseline_axis_means": avg_a, "candidate_axis_means": avg_b,
        "candidate_minus_baseline": {k: round(avg_b[k] - avg_a[k], 3) for k in AXES},
        "baseline_overall_mean": total_a, "candidate_overall_mean": total_b,
        "overall_delta": round(total_b - total_a, 3),
        "baseline_p50_ttft_ms": baseline["summary"]["p50_first_content_ms"],
        "candidate_p50_ttft_ms": candidate["summary"]["p50_first_content_ms"],
        "decision": "HUMAN_REVIEW_REQUIRED",
        "interpretation": "Subjective one-reviewer comparison, not an objective model leaderboard.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="Opt-in 8-case live roleplay suite")
    p.add_argument("--agent-url", type=client.loopback_origin, default=client.DEFAULT_AGENT)
    p.add_argument("--expect-model", required=True,
                   help="Required case-insensitive substring of REAL Agent model identity")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--review-file", type=Path, required=True)
    p.add_argument("--max-tokens", type=int, default=512, choices=range(64, 513))
    p.add_argument("--timeout", type=int, default=180, choices=range(15, 601))
    p = sub.add_parser("score", help="Local interactive human rubric scoring")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--review-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("compare", help="Compare scored reports from DIFFERENT actual models")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--baseline-scores", type=Path, required=True)
    p.add_argument("--candidate-scores", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run(args.agent_url, args.output, args.review_file,
                         args.expect_model, args.max_tokens, args.timeout)
            print(json.dumps({"status": result["status"], "runtime_model": result["runtime"]["model"],
                              "summary": result["summary"], "error_code": result["error_code"],
                              "error_phase": result["error_phase"], "output": str(args.output)},
                             indent=2, ensure_ascii=False))
            return 0 if result["status"] == "complete" else 1
        if args.command == "score":
            result = score(args.report, args.review_file, args.output)
            print(f"Saved {len(result['scores'])} private ratings to {args.output}")
            return 0
        if args.output:
            client.fresh_paths([args.output])
        paths = [args.baseline, args.candidate, args.baseline_scores, args.candidate_scores]
        if any(p.stat().st_size > 2_000_000 for p in paths):
            raise ValueError("Report too large")
        result = compare(*[json.loads(p.read_text(encoding="utf-8")) for p in paths])
        if args.output:
            client.write_private(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        # Do not reveal model output, URL, request content or private exception text.
        print(f"NSFW benchmark command failed: {type(exc).__name__} (details withheld)",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
