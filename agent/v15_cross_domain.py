"""Opt-in, honest cross-domain V15 live evaluation on an explicit loopback agent.

The automated report measures mechanics, not factual correctness. Human review
of relevance, accuracy, completeness, citations and safe uncertainty is
required before describing a native run as a quality pass.

Usage:
  python -m agent.v15_cross_domain run --limit 3
  python -m agent.v15_cross_domain run
  python -m agent.v15_cross_domain score --run-dir artifacts/performance/...
"""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics

from agent.live_capture import capture, validate_url

SUITE_FILE = Path(__file__).resolve().parent.parent / "tests/fixtures/v15_cross_domain_live.json"
DEFAULT_ENDPOINT = "http://127.0.0.1:8010/api/agent/run"
REVIEW_COLUMNS = ("id", "category", "question", "review_criteria", "relevance",
                  "accuracy", "completeness", "citations", "safe_uncertainty", "notes")
REVIEW_DIMENSIONS = REVIEW_COLUMNS[4:-1]


def suite_cases(path=SUITE_FILE):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = doc.get("cases")
    if (not isinstance(cases, list) or len(cases) < 8
            or not isinstance(doc.get("suite"), str)):
        raise ValueError("Expected a frozen 8+ case cross-domain suite")
    ids = [c.get("id") for c in cases if isinstance(c, dict)]
    if (len(ids) != len(cases) or len(set(ids)) != len(ids)
            or any(not isinstance(c.get("question"), str) or not c["question"].strip()
                   or not c.get("category") or not c.get("review_criteria")
                   for c in cases)):
        raise ValueError("Case IDs and research questions must be nonempty and unique")
    if len({c["category"] for c in cases}) < 7:
        raise ValueError("Need at least seven distinct topical categories")
    return cases


def _percentile(values, fraction):
    """Nearest-rank tail percentile, without extrapolating a tiny cohort."""
    if not values:
        return None
    sorted_values = sorted(values)
    return sorted_values[max(0, math.ceil(fraction * len(sorted_values)) - 1)]


def _steps(response):
    steps = response.get("steps", []) if isinstance(response, dict) else []
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def case_technical(row):
    response = row.get("response")
    response = response if isinstance(response, dict) else {}
    evidence = response.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    step_list = _steps(response)
    source_urls = set()
    search_providers = set()
    for step in step_list:
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        if step.get("action") in {"search_web", "web_search"}:
            if isinstance(result.get("provider"), str):
                search_providers.add(result["provider"])
        if step.get("action") == "fetch_url" and result.get("ok") is True:
            url = result.get("final_url") or result.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                source_urls.add(url)
    events = response.get("performance")
    events = events.get("events", []) if isinstance(events, dict) else []
    model_events = [event for event in events if isinstance(event, dict)
                    and event.get("action") == "provider.complete"] if isinstance(events, list) else []
    model_ms = sum(float(event["duration_ms"]) for event in model_events
                   if type(event.get("duration_ms")) in (int, float)
                   and math.isfinite(event["duration_ms"]) and event["duration_ms"] >= 0)
    elapsed = row.get("elapsed_ms")
    elapsed = float(elapsed) if type(elapsed) in (int, float) and math.isfinite(elapsed) else None
    claims = evidence.get("claims")
    claims = claims if isinstance(claims, list) else []
    supported = evidence.get("verified_supported_count")
    supported = supported if type(supported) is int and supported >= 0 else 0
    return {
        "id": row.get("id"), "category": row.get("category"),
        "completed": response.get("status") == "completed" and "error" not in row,
        "error": row.get("error"),
        "elapsed_ms": elapsed,
        "search_actions": sum(s.get("action") in {"search_web", "web_search"} for s in step_list),
        "fetch_actions": sum(s.get("action") == "fetch_url" for s in step_list),
        "loaded_source_count": len(source_urls),
        "search_providers": sorted(search_providers),
        "verified_supported_count": supported,
        "audited_claim_count": len(claims),
        "evidence_error": evidence.get("error_status"),
        "model_calls": len(model_events),
        "model_ms": round(model_ms, 2),
        "unattributed_ms": round(max(0, elapsed - model_ms), 2) if elapsed is not None else None,
        "model_call_ms_by_purpose": _purpose_durations(model_events),
    }


def _purpose_durations(events):
    durations = {}
    for event in events:
        purpose = event.get("purpose")
        duration = event.get("duration_ms")
        if not isinstance(purpose, str) or not isinstance(duration, (int, float)):
            continue
        if not math.isfinite(duration) or duration < 0:
            continue
        durations[purpose] = round(durations.get(purpose, 0) + duration, 2)
    return durations


def technical_summary(rows):
    measures = [case_technical(r) for r in rows]
    elapsed = [m["elapsed_ms"] for m in measures if m["elapsed_ms"] is not None]
    by_purpose = {}
    for row in measures:
        for purpose, duration in row["model_call_ms_by_purpose"].items():
            by_purpose[purpose] = round(by_purpose.get(purpose, 0) + duration, 2)
    total_elapsed = sum(elapsed)
    model_total = sum(m["model_ms"] for m in measures)
    return {
        "method": "technical_observations_only_not_independent_truth_or_relevance",
        "total": len(measures), "completed": sum(m["completed"] for m in measures),
        "errors": sum(not m["completed"] for m in measures),
        "zero_supported_cases": sum(m["verified_supported_count"] == 0 for m in measures),
        "cases_with_loaded_sources": sum(m["loaded_source_count"] > 0 for m in measures),
        "latency_median_ms": round(statistics.median(elapsed), 2) if elapsed else None,
        "latency_p95_nearest_rank_ms": _percentile(elapsed, .95),
        "model_ms_total": round(model_total, 2),
        "model_time_fraction": round(model_total / total_elapsed, 3) if total_elapsed else None,
        "model_ms_by_purpose": by_purpose,
        "cases": measures,
        "quality_status": "unreviewed",
        "warning": ("A completed response, source count or supported claim count "
                    "is NOT proof of factual accuracy, relevance or answer completeness."),
    }


def create_review_csv(cases, path):
    with Path(path).open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for c in cases:
            writer.writerow({"id": c["id"], "category": c["category"],
                             "question": c["question"],
                             "review_criteria": c["review_criteria"],
                             **{col: "" for col in REVIEW_DIMENSIONS},
                             "notes": ""})


def score_reviews(path, expected_ids):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(REVIEW_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("Review CSV missing required columns")
        reviews = list(reader)
    ids = [row["id"] for row in reviews]
    if len(set(ids)) != len(ids) or set(ids) != set(expected_ids):
        raise ValueError("Reviews must match the attempted run's case IDs exactly")
    completed, pending = [], []
    for row in reviews:
        values = [row[dim].strip() for dim in REVIEW_DIMENSIONS]
        if not any(values):
            pending.append(row["id"])
            continue
        if any(v not in {"0", "1", "2"} for v in values):
            raise ValueError("Each reviewed case needs integer 0, 1 or 2 in ALL five dimensions")
        completed.append({**row, **{d: int(row[d]) for d in REVIEW_DIMENSIONS}})
    return {
        "reviewed": len(completed), "pending": pending,
        "complete": not pending,
        "fully_acceptable": (not pending and all(
            all(row[dimension] == 2 for dimension in REVIEW_DIMENSIONS)
            for row in completed)),
        "scores": {dimension: (round(sum(r[dimension] for r in completed)
                                    / len(completed), 3) if completed else None)
                   for dimension in REVIEW_DIMENSIONS},
        "case_reviews": completed,
        "quality_status": "reviewed" if not pending else "partially_reviewed",
    }


def run_suite(*, endpoint=DEFAULT_ENDPOINT, output_dir, limit=None, timeout=180,
              capture_fn=capture, cases=None):
    validate_url(endpoint)
    selected = list(cases if cases is not None else suite_cases())
    if limit is not None:
        if type(limit) is not int or limit < 1:
            raise ValueError("Limit must be a positive integer")
        selected = selected[:limit]
    if not selected:
        raise ValueError("No cases selected")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    with (output_dir / "capture.jsonl").open("x", encoding="utf-8") as dest:
        for i, case in enumerate(selected, 1):
            print(f"[{i}/{len(selected)}] {case['id']} {case['category']}", flush=True)
            result = capture_fn([case["question"]], endpoint, timeout=timeout)[0]
            row = {**result, "id": case["id"], "category": case["category"]}
            rows.append(row)
            dest.write(json.dumps(row, ensure_ascii=False) + "\n")
            dest.flush()
            print(f"  elapsed={row.get('elapsed_ms')}ms "
                  f"supported={case_technical(row)['verified_supported_count']} "
                  f"error={row.get('error') or '-'}", flush=True)
    create_review_csv(selected, output_dir / "human_review.csv")
    summary = technical_summary(rows)
    summary["suite"] = "v15-cross-domain-unseen-1"
    summary["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
    (output_dir / "technical_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "cases.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    run.add_argument("--output-dir", type=Path, default=None)
    run.add_argument("--limit", type=int)
    run.add_argument("--timeout", type=float, default=180)
    score = sub.add_parser("score")
    score.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "run":
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            parser.error("--timeout must be finite and positive")
        target = args.output_dir or Path("artifacts/performance") / (
            "v15-cross-domain-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
        summary = run_suite(endpoint=args.endpoint, output_dir=target,
                            limit=args.limit, timeout=args.timeout)
        print(json.dumps({"output_dir": str(target),
                          "total": summary["total"],
                          "completed": summary["completed"],
                          "latency_median_ms": summary["latency_median_ms"],
                          "latency_p95_nearest_rank_ms": summary["latency_p95_nearest_rank_ms"],
                          "quality_status": summary["quality_status"]},
                         ensure_ascii=False, indent=2))
    else:
        directory = args.run_dir
        cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
        result = score_reviews(directory / "human_review.csv", [c["id"] for c in cases])
        (directory / "human_review_summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "case_reviews"},
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
