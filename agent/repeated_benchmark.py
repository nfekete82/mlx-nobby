"""Repeat local agent captures and report latency plus heuristic review flags.

No remote endpoints, no automated accuracy claims, and no source contents in
the summary. Raw captures are local and may contain sensitive information.
"""
import argparse
import json
import math
import platform
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from agent.live_capture import capture, validate_url
from agent.model_efficiency import model_efficiency
from agent.temporal_validation import future_availability_conflicts


def latency_summary(values):
    """Nearest-rank p95; report sample count so small cohorts are explicit."""
    values = sorted(values)
    return {"samples": len(values),
            "median_ms": round(median(values), 2) if values else None,
            "p95_ms": round(values[math.ceil(.95 * len(values)) - 1], 2) if values else None,
            "min_ms": round(values[0], 2) if values else None,
            "max_ms": round(values[-1], 2) if values else None}


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
            try:
                captured_day = datetime.fromisoformat(record["captured_at"]).date()
            except (KeyError, TypeError, ValueError):
                captured_day = None
            if future_availability_conflicts(answer, captured_day):
                flags.append("future_date_inconsistency")
            if "**Zeitprüfung:**" in answer:
                flags.append("temporal_warning")
            if "**Quellenprüfung:**" in answer:
                flags.append("evidence_warning")
            if "**Linkprüfung:**" in answer:
                flags.append("citation_warning")
            if "**Evidenzstatus:**" in answer:
                flags.append("missing_article_evidence")
        steps = response.get("steps") or []
        fetched = sum(isinstance(s, dict) and s.get("action") == "fetch_url"
                      and s.get("status") == "completed" for s in steps)
        if isinstance(answer, str) and "Quellen:" in answer and fetched == 0:
            flags.append("source_claim_without_fetch")
        efficiency = model_efficiency(response)
        phases = {}
        performance = response.get("performance")
        events = performance.get("events", []) if isinstance(performance, dict) else []
        for event in events if isinstance(events, list) else []:
            if isinstance(event, dict) and event.get("phase") == "model_hook":
                action = event.get("action")
                if action in {"agent_choose_next_step_v2", "agent_v2_final_answer", "agent_llm"}:
                    phases[action] = phases.get(action, 0) + 1
        evidence = response.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        evidence_timings = evidence.get("timings_ms", {})
        evidence_timings = evidence_timings if isinstance(evidence_timings, dict) else {}
        supported_count = evidence.get("verified_supported_count", evidence.get("selected_count"))
        supported_count = supported_count if type(supported_count) is int and supported_count >= 0 else None
        if evidence.get("method") and supported_count == 0:
            flags.append("no_verified_facts")
        evidence_claims = evidence.get("claims", [])
        evidence_statuses = {status: sum(isinstance(c, dict) and c.get("status") == status for c in evidence_claims)
                             for status in ("supported", "contradicted", "insufficient_evidence", "conflicting_evidence", "not_checked")} if isinstance(evidence_claims, list) else {}
        research_ms = sum(event.get("duration_ms", 0) for event in events
                          if isinstance(event, dict) and event.get("phase") == "tool"
                          and event.get("action") in {"search_web", "web_search", "fetch_url"}
                          and type(event.get("duration_ms")) in (int, float)
                          and math.isfinite(event["duration_ms"]) and event["duration_ms"] >= 0) if isinstance(events, list) else 0
        totals = {key: round(sum(call.get(key, 0) for call in efficiency["calls"]), 2)
                  for key in ("lease_wait_ms", "lock_wait_ms", "model_setup_ms", "upstream_request_ms")}
        findings.append({
            "id": record["id"], "question_index": record.get("question_index", 1),
            "status": "ok" if record in ok else "error",
            "latency_ms": record.get("elapsed_ms"),
            "model_calls": efficiency["call_count"], "model_phases": phases,
            "timings_ms": totals, "calls": efficiency["calls"],
            "known_prompt_tokens": efficiency["known_prompt_tokens"],
            "known_completion_tokens": efficiency["known_completion_tokens"],
            "known_total_tokens": sum(call.get("total_tokens", 0) for call in efficiency["calls"]),
            "fetches": fetched, "heuristic_flags": flags,
            "research_ms": round(research_ms, 2),
            "evidence_timings_ms": {key: round(value, 2) for key, value in evidence_timings.items()
                                    if key in {"extraction", "verification"} and type(value) in (int, float)
                                    and math.isfinite(value) and value >= 0},
            "quality_review": "manual_review_required",
            "verified_supported_count": supported_count,
            "claim_status_counts": evidence_statuses,
            "evidence_method": evidence.get("method") if evidence.get("method") in {"anchored_extractive", "model_semantic_verification"} else None,
        })
    return {
        "status": "heuristic_review_only",
        "attempted": len(records), "completed": len(ok),
        "errors": len(records) - len(ok),
        "error_rate": (len(records) - len(ok)) / len(records) if records else 0.0,
        **latency_summary(latencies),
        "per_question": {str(index): latency_summary([
            case["latency_ms"] for case in findings
            if case["question_index"] == index and case["status"] == "ok"])
            for index in sorted({case["question_index"] for case in findings})},
        "cases": findings,
        "caveat": "Flags are not fact verification; inspect each answer and its actual sources.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8010/api/agent/run")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--model-label", default="unknown")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args(argv)
    validate_url(args.endpoint)
    if not 1 <= args.repeats <= 5 or not math.isfinite(args.timeout) or args.timeout <= 0 or not 1 <= args.concurrency <= 4:
        parser.error("repeats must be 1..5, concurrency 1..4 and timeout finite and > 0")
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not questions or len(questions) > 20:
        parser.error("questions must be a list of 1..20 strings")
    if any(not isinstance(q, str) or not q.strip() for q in questions):
        parser.error("questions must be nonempty strings")
    prefix = Path(args.output_prefix)
    raw = prefix.with_name(prefix.name + ".jsonl")
    report = prefix.with_name(prefix.name + "-report.json")
    if raw.exists() or report.exists():
        parser.error("output exists; refusing to overwrite")
    started_at = datetime.now(timezone.utc).isoformat()
    jobs = [(repeat, index, question) for repeat in range(args.repeats)
            for index, question in enumerate(questions, 1)]

    def run(job):
        repeat, index, question = job
        record = capture([question], args.endpoint, timeout=args.timeout)[0]
        record.update(id=f"run-{repeat + 1}-live-{index:03d}", question_index=index,
                      captured_at=datetime.now(timezone.utc).isoformat())
        return record

    records = []
    # Reserve both destinations before the first request. Persist completed
    # captures incrementally, including errors, if a later request is interrupted.
    with raw.open("x", encoding="utf-8") as handle:
        with report.open("x", encoding="utf-8") as report_handle:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                for record in pool.map(run, jobs):
                    records.append(record)
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
            summary = summarize_runs(records)
            summary["conditions"] = {"started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "load_kind": "sequential" if args.concurrency == 1 else "parallel",
                "concurrency": args.concurrency, "repeats": args.repeats,
                "timeout_seconds": args.timeout, "model_label": args.model_label,
                "machine": platform.machine(), "system": platform.system(),
                "python": platform.python_version(), "cpu_count": os.cpu_count()}
            json.dump(summary, report_handle, ensure_ascii=False, indent=2)
            report_handle.write("\n")
    print(json.dumps({k: summary[k] for k in
                      ("attempted", "completed", "errors", "median_ms", "min_ms", "max_ms")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
