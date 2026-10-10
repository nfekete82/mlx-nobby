"""Repeat local agent captures and report latency plus heuristic review flags.

No remote endpoints, no automated accuracy claims, and no source contents in
the summary. Raw captures are local and may contain sensitive information.
"""
import argparse
import json
from pathlib import Path
from statistics import median
from agent.live_capture import capture, validate_url
from agent.model_efficiency import model_efficiency
from agent.temporal_validation import future_availability_conflicts


def summarize_runs(records):
    ok = [r for r in records if r.get("review_status") == "pending"
          and isinstance(r.get("response"), dict)]
    latencies = [r["elapsed_ms"] for r in ok]
    findings = []
    for record in records:
        response = record.get("response") or {}
        answer = response.get("answer", "")
        flags = []
        if isinstance(answer, str):
            if future_availability_conflicts(answer):
                flags.append("future_date_inconsistency")
            if "**Zeitprüfung:**" in answer:
                flags.append("temporal_warning")
        steps = response.get("steps") or []
        fetched = sum(isinstance(s, dict) and s.get("action") == "fetch_url"
                      and s.get("status") == "completed" for s in steps)
        if isinstance(answer, str) and "Quellen:" in answer and fetched == 0:
            flags.append("source_claim_without_fetch")
        findings.append({
            "id": record["id"], "question": record["question"],
            "status": "ok" if record in ok else "error",
            "latency_ms": record.get("elapsed_ms"),
            "model_calls": model_efficiency(response)["call_count"],
            "fetches": fetched, "heuristic_flags": flags,
        })
    return {
        "status": "heuristic_review_only",
        "attempted": len(records), "completed": len(ok),
        "errors": len(records) - len(ok),
        "median_ms": round(median(latencies), 2) if latencies else None,
        "min_ms": round(min(latencies), 2) if latencies else None,
        "max_ms": round(max(latencies), 2) if latencies else None,
        "cases": findings,
        "caveat": "Flags are not fact verification; inspect each answer and its actual sources.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8010/api/agent/run")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args(argv)
    validate_url(args.endpoint)
    if not 1 <= args.repeats <= 5 or args.timeout <= 0:
        parser.error("repeats must be 1..5 and timeout > 0")
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions or len(questions) > 20:
        parser.error("questions must be a list of 1..20 strings")
    prefix = Path(args.output_prefix)
    raw = prefix.with_name(prefix.name + ".jsonl")
    report = prefix.with_name(prefix.name + "-report.json")
    if raw.exists() or report.exists():
        parser.error("output exists; refusing to overwrite")
    records = []
    for repeat in range(args.repeats):
        for record in capture(questions, args.endpoint, timeout=args.timeout):
            record["id"] = f"run-{repeat + 1}-{record['id']}"
            records.append(record)
    summary = summarize_runs(records)
    with raw.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with report.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({k: summary[k] for k in
                      ("attempted", "completed", "errors", "median_ms", "min_ms", "max_ms")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
