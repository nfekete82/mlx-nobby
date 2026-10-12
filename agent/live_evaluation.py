"""Offline evaluator for manually reviewed live-research transcripts.

Consumes JSONL records captured from real runs. Never calls a model/network and
never presents heuristic scores as ground-truth factual accuracy.

Usage:
    python -m agent.live_evaluation input.jsonl --output report.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean

LABELS = {"correct", "incorrect", "unverifiable", "not_answered"}
REQUIRED = {"id", "question", "reference_urls", "before", "after", "review"}


def _safe_record(item, seen):
    if not isinstance(item, dict) or not REQUIRED <= set(item):
        raise ValueError("Missing required fields")
    ident = item["id"]
    if not isinstance(ident, str) or not ident.strip() or ident in seen:
        raise ValueError("Duplicate or invalid ID")
    seen.add(ident)
    if not isinstance(item["question"], str) or not item["question"].strip():
        raise ValueError("Question missing")
    urls = item["reference_urls"]
    if not isinstance(urls, list) or not urls or not all(
        isinstance(u, str) and u.startswith("https://") for u in urls
    ):
        raise ValueError("Explicit HTTPS reference URLs required")
    for key in ("before", "after"):
        if not isinstance(item[key], dict):
            raise ValueError(key + " must be an object")
        if not isinstance(item[key].get("answer"), str):
            raise ValueError(key + ".answer missing")
        elapsed = item[key].get("elapsed_ms")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (float, int)) or elapsed < 0:
            raise ValueError(key + ".elapsed_ms must be nonnegative")
    review = item["review"]
    if not isinstance(review, dict) or review.get("before") not in LABELS or review.get("after") not in LABELS:
        raise ValueError("Review labels required")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("Reviewer required")
    return item


def load_records(path):
    seen, records = set(), []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = _safe_record(json.loads(line), seen)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Line {line_no}: {exc}") from exc
        records.append(item)
    if not records:
        raise ValueError("No evaluated records")
    return records


def summarize(records):
    before = Counter(r["review"]["before"] for r in records)
    after = Counter(r["review"]["after"] for r in records)
    transitions = Counter(
        r["review"]["before"] + " -> " + r["review"]["after"] for r in records
    )
    fixed = sum(r["review"]["before"] == "incorrect" and
                r["review"]["after"] == "correct" for r in records)
    regressions = sum(r["review"]["before"] == "correct" and
                      r["review"]["after"] != "correct" for r in records)
    before_latency = mean(r["before"]["elapsed_ms"] for r in records)
    after_latency = mean(r["after"]["elapsed_ms"] for r in records)
    return {
        "dataset": "manual-live-review", "cases": len(records),
        "labels_before": dict(before), "labels_after": dict(after),
        "transitions": dict(sorted(transitions.items())),
        "incorrect_to_correct": fixed, "correct_to_noncorrect": regressions,
        "correct_rate_before": before["correct"] / len(records),
        "correct_rate_after": after["correct"] / len(records),
        "mean_before_ms": round(before_latency, 2),
        "mean_after_ms": round(after_latency, 2),
        "mean_added_ms": round(after_latency - before_latency, 2),
        "caveat": "Reviewer judgments, not independent automated fact verification."
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Reviewed live-run JSONL file")
    parser.add_argument("--output", help="JSON output path; prints if omitted")
    args = parser.parse_args(argv)
    report = json.dumps(summarize(load_records(args.input)), indent=2,
                        ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
