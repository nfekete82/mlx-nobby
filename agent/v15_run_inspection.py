"""Read-only inspection of existing V15 native cross-domain captures.

Shows search providers, actual source fetches, evidence outcomes, rough
time attribution and the final answer. Never reruns the agent, fabricates
quality labels, or prints full fetched article text/URL query parameters.

Run: python -m agent.v15_run_inspection --run-dir artifacts/performance/...
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from agent.v15_cross_domain import case_technical
from agent.model_efficiency import model_efficiency


def _short(value, limit=260):
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def _source_locator(url):
    """Only URL hostname/path for diagnostic output, never query parameters."""
    if not isinstance(url, str) or len(url) > 4096:
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        return parts.hostname.lower() + _short(parts.path, 130)
    except ValueError:
        return ""


def inspect_case(row):
    """Extract observations, not guesses about the root cause."""
    if not isinstance(row, dict):
        raise ValueError("Each capture record must be a JSON object")
    result = case_technical(row)
    response = row.get("response") if isinstance(row.get("response"), dict) else {}
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else None
    steps = response.get("steps")
    steps = steps if isinstance(steps, list) else []
    traces = []
    fetched = 0
    for step in steps[:18]:
        if not isinstance(step, dict):
            continue
        action = step.get("action")
        observed = step.get("result") if isinstance(step.get("result"), dict) else {}
        entry = {"action": action, "status": step.get("status")}
        if action in {"search_web", "web_search"}:
            hits = observed.get("results")
            hits = hits if isinstance(hits, list) else []
            engines = observed.get("unresponsive_engines")
            engines = engines if isinstance(engines, list) else []
            entry.update({
                "query": _short(step.get("query"), 140),
                "provider": observed.get("provider"),
                "provider_status": observed.get("provider_status"),
                "degraded": observed.get("search_degraded"),
                "hit_count": observed.get("count", len(hits)),
                "first_hits": [
                    {"source": _source_locator(hit.get("url")),
                     "title": _short(hit.get("title"), 105)}
                    for hit in hits[:5] if isinstance(hit, dict)
                ],
                "unresponsive": [
                    {"engine": _short(engine.get("engine"), 60),
                     "status": engine.get("status")}
                    for engine in engines[:5] if isinstance(engine, dict)
                ],
            })
        elif action == "fetch_url":
            if observed.get("ok") is True:
                fetched += 1
            body = observed.get("text")
            entry.update({
                "source": _source_locator(observed.get("final_url") or observed.get("url")
                                          or step.get("query")),
                "ok": observed.get("ok"),
                "text_chars": len(body) if isinstance(body, str) else 0,
                "content_type": _short(observed.get("content_type"), 75),
                "link_count": len(observed.get("page_links") or [])
                    if isinstance(observed.get("page_links"), list) else 0,
                "total_characters": observed.get("total_characters"),
                "truncated": observed.get("truncated"),
                "has_release_heading": bool(
                    isinstance(body, str) and re.search(
                        r"(?i)active python releases|latest python 3 release|"
                        r"python releases by version number|stable releases",
                        body,
                    )
                ),
                "retrieval_status": observed.get("retrieval_status"),
                "error": _short(observed.get("error"), 170),
            })
        else:
            entry["reason"] = _short(step.get("reason"), 140)
        traces.append(entry)
    claims = evidence.get("claims") if evidence else None
    claims = claims if isinstance(claims, list) else []
    error_status = evidence.get("error_status") if evidence else None
    if result["error"]:
        hint = "transport_or_agent_error"
    elif evidence is None:
        hint = "no_evidence_audit"
    elif error_status == "no_usable_evidence":
        # No fetched source passages is a *valid abstention*, not a model
        # serialization/crash error. Preserve the underlying reason verbatim.
        hint = "no_usable_source_evidence"
    elif error_status:
        hint = "evidence_processing_error"
    elif not fetched:
        hint = "no_successfully_fetched_sources"
    elif (evidence.get("extraction_method") == "derived_statutory_workweek_conversion"
          and evidence.get("method") == "source_anchored_arithmetic"
          and result["verified_supported_count"] > 0):
        hint = "deterministic_source_anchored_calculation"
    elif not claims:
        hint = "no_extracted_claims_or_valid_abstention"
    elif (result["verified_supported_count"] == 0
          and any(isinstance(c, dict)
                  and c.get("decision_origin") == "invalid_response"
                  for c in claims)):
        # A model-format/protocol failure is not the same as contradictory
        # source evidence. Keep the original fail-closed result unchanged.
        hint = "verifier_invalid_response"
    elif result["verified_supported_count"] == 0:
        hint = "candidate_verification_or_abstention"
    else:
        hint = "model_supported_claims_require_independent_review"
    return {
        "id": row.get("id"),
        "category": row.get("category"),
        "question": row.get("question"),
        "status": response.get("status"),
        "elapsed_ms": result["elapsed_ms"],
        "supported_count": result["verified_supported_count"],
        "evidence_present": evidence is not None,
        "evidence_error": error_status,
        "source_count": result["loaded_source_count"],
        "model_calls": result["model_calls"],
        "model_ms_by_purpose": result["model_call_ms_by_purpose"],
        "model_call_details": model_efficiency(response)["calls"],
        "unattributed_ms": result["unattributed_ms"],
        "stage_hint": hint,
        "steps": traces,
        "claim_decisions": [
            {"status": claim.get("status"),
             "subject": _short(claim.get("subject"), 100),
             "reason": _short(claim.get("reason"), 220)}
            for claim in claims[:10] if isinstance(claim, dict)
        ],
        "answer": _short(response.get("answer"), 2000),
        "run_error": _short(row.get("error"), 180),
        "quality_status": "requires_independent_human_review",
    }


def inspect_run(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Capture file not found")
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                if len(rows) >= 100:
                    raise ValueError("Capture exceeds 100 records")
                rows.append(inspect_case(json.loads(line)))
    if not rows:
        raise ValueError("Empty capture")
    return {"method": "retrospective_observations_only",
            "total": len(rows),
            "independent_accuracy_verified": False,
            "cases": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_run(args.run_dir / "capture.jsonl")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Inspection failed: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
