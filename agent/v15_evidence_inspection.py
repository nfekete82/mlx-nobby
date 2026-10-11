"""Offline diagnostics of exactly the evidence supplied to native extraction.

Reads saved, already fetched pages from capture.jsonl. No network/LLM calls,
no mutation, no re-run. Content-bearing excerpts are shortened and optional
because web pages are untrusted and may contain user-specific data.
"""
import argparse
import json
from pathlib import Path

from agent.catalog_evidence import catalog_source_windows
from agent.research_followup import support_policy_windows
from agent.structured_evidence import build_evidence


def evidence_inspection(row):
    goal = str(row.get("question") or "")
    response = row.get("response")
    response = response if isinstance(response, dict) else {}
    observations = response.get("steps")
    observations = observations if isinstance(observations, list) else []
    bundle = build_evidence(observations, goal=goal)
    reports = []
    for source in bundle.sources:
        entries = [f for f in bundle.facts if f.source_id == source.id]
        catalog = catalog_source_windows(goal, source.text)
        support = support_policy_windows(goal, source.text)
        rows = source.text.splitlines()
        header_rows = [
            i for i, text in enumerate(rows)
            if ("supported" in text.lower() and "version" in text.lower())
            or ("modell" in text.lower() and "pixel" in text.lower())
        ][:4]
        reports.append({
            "url": source.final_url,
            "status": source.retrieval_status,
            "text_chars": len(source.text),
            "anchored_passage_count": len(entries),
            "anchored_passage_chars": sum(len(f.evidence_excerpt) for f in entries),
            "catalog_window_count": len(catalog),
            "support_window_count": len(support),
            "support_row_locations": header_rows,
            "source_hint": (
                "support_header_not_detected" if "version" in goal.lower() and not support
                else "catalog_heading_not_detected" if "Pixel" in goal and not catalog
                else "structured_window_present"
            ),
            "support_line_sample": [
                str(rows[i])[:220] for i in header_rows
            ],
        })
    return {"case_id": row.get("id"), "question": goal,
            "fetched_source_count": len(bundle.sources), "sources": reports,
            "warning": "Offline source-shape diagnostics only, not a semantic truth assessment"}


def inspect_saved_capture(path):
    cases = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for i, line in enumerate(handle):
            if i >= 100:
                raise ValueError("Too many cases")
            if line.strip():
                cases.append(evidence_inspection(json.loads(line)))
    return {"cases": cases, "reads_only_saved_capture": True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    args = p.parse_args(argv)
    report = inspect_saved_capture(args.run_dir / "capture.jsonl")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
