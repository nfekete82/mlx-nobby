"""Retrospective V15 diagnosis does not rerun or invent root causes."""
import json

import pytest

from agent.v15_run_inspection import inspect_case, inspect_run, _source_locator


def row(*, search=True, fetch=True, evidence=True, error=None):
    steps = []
    if search:
        steps.append({"action": "search_web", "status": "completed",
                      "query": "official products",
                      "result": {"provider": "SearXNG", "provider_status": "available",
                                 "search_degraded": False, "count": 1,
                                 "results": [{
                                     "title": "Official entry",
                                     "url": "https://example.org/search/path?token=secret",
                                 }]}})
    if fetch:
        steps.append({"action": "fetch_url", "status": "completed",
                      "query": "https://example.org/article?token=secret",
                      "result": {"ok": True,
                                 "url": "https://example.org/article?token=secret",
                                 "text": "DO_NOT_DUMP_RAW_WEB_SOURCE" * 10}})
    result = {"id": "CD01", "category": "products", "question": "What products?",
              "elapsed_ms": 1500,
              "response": {"status": "completed", "answer": "Not enough evidence.",
                           "steps": steps,
                           "performance": {"events": [
                               {"action": "provider.complete",
                                "purpose": "agent.plan", "duration_ms": 100},
                               {"action": "provider.complete",
                                "purpose": "agent.extract", "duration_ms": 300},
                           ]}}}
    if evidence:
        result["response"]["evidence"] = {
            "verified_supported_count": 0, "error_status": None,
            "claims": [{"status": "insufficient_evidence",
                        "subject": "Phone",
                        "reason": "Official listing not established."}],
        }
    if error:
        result["error"] = error
    return result


def test_inspects_existing_search_and_fetch_without_dumping_text_or_url_tokens():
    report = inspect_case(row())
    assert report["evidence_present"]
    assert report["stage_hint"] == "candidate_verification_or_abstention"
    assert report["model_ms_by_purpose"] == {
        "agent.plan": 100, "agent.extract": 300,
    }
    assert report["unattributed_ms"] == 1100
    assert [call["purpose"] for call in report["model_call_details"]] == ["agent.plan", "agent.extract"]
    assert [call["duration_ms"] for call in report["model_call_details"]] == [100, 300]
    assert report["steps"][0]["first_hits"][0]["source"] == "example.org/search/path"
    assert report["steps"][1]["source"] == "example.org/article"
    serialized = json.dumps(report)
    assert "DO_NOT_DUMP_RAW_WEB_SOURCE" not in serialized
    assert "token=secret" not in serialized
    assert "Official listing not established." in serialized
    assert report["quality_status"] == "requires_independent_human_review"


def test_distinguishes_no_audit_empty_candidates_and_fetch_failures():
    assert inspect_case(row(evidence=False))["stage_hint"] == "no_evidence_audit"
    no_claims = row()
    no_claims["response"]["evidence"]["claims"] = []
    assert inspect_case(no_claims)["stage_hint"] == "no_extracted_claims_or_valid_abstention"
    no_fetch = row(fetch=False)
    assert inspect_case(no_fetch)["stage_hint"] == "no_successfully_fetched_sources"
    bad = row(error="agent_status:failed")
    assert inspect_case(bad)["stage_hint"] == "transport_or_agent_error"
    extraction = row()
    extraction["response"]["evidence"]["error_status"] = "invalid_extraction_schema"
    assert inspect_case(extraction)["stage_hint"] == "evidence_processing_error"
    abstained = row(search=True, fetch=False)
    abstained["response"]["evidence"]["error_status"] = "no_usable_evidence"
    report = inspect_case(abstained)
    assert report["stage_hint"] == "no_usable_source_evidence"
    assert report["evidence_error"] == "no_usable_evidence"


def test_reuses_saved_jsonl_only_and_rejects_missing_capture(tmp_path):
    path = tmp_path / "capture.jsonl"
    path.write_text(json.dumps(row()) + "\n" + json.dumps(row(evidence=False)) + "\n",
                    encoding="utf-8")
    report = inspect_run(path)
    assert report["total"] == 2
    assert report["independent_accuracy_verified"] is False
    assert len(report["cases"]) == 2
    with pytest.raises(ValueError, match="not found"):
        inspect_run(tmp_path / "missing.jsonl")


def test_invalid_result_rejected():
    with pytest.raises(ValueError, match="object"):
        inspect_case([{"id": "CD01"}])
    assert _source_locator("https://user:pass@example.org/safe?secret=q") == "example.org/safe"
    assert _source_locator("not a url") == ""


def test_per_call_telemetry_is_numeric_only_and_does_not_disclose_prompt():
    record = row()
    record["response"]["performance"]["events"] = [
        {"action": "provider.complete", "purpose": "agent.verify",
         "duration_ms": 35580.9, "input_chars": 12345,
         "prompt_tokens": 3098, "completion_tokens": 260,
         "queue_wait_ms": 25.0, "upstream_request_ms": 35000,
         "private_prompt": "DO_NOT_ECHO_SENSITIVE_PROMPT"},
    ]
    calls = inspect_case(record)["model_call_details"]
    assert calls == [{
        "duration_ms": 35580.9,
        "input_chars": 12345,
        "prompt_tokens": 3098,
        "completion_tokens": 260,
        "queue_wait_ms": 25.0,
        "upstream_request_ms": 35000,
        "purpose": "agent.verify",
    }]
    assert "DO_NOT_ECHO_SENSITIVE_PROMPT" not in str(calls)



def test_fetch_diagnostic_shows_content_type_and_links_without_raw_html():
    record = row()
    evidence = record["response"]["steps"][1]["result"]
    evidence.update({
        "content_type": "text/html; charset=UTF-8",
        "text": "Active Python releases. DO_NOT_DUMP_RAW_WEB_SOURCE " * 8,
        "page_links": [{
            "url": "https://www.python.org/downloads/release/python-3150/?token=secret",
            "title": "Python 3.15.0",
        }],
        "truncated": False, "total_characters": 2145,
    })
    step = inspect_case(record)["steps"][1]
    assert step["content_type"].startswith("text/html")
    assert step["has_release_heading"] is True
    assert step["link_count"] == 1
    assert step["total_characters"] == 2145
    assert step["truncated"] is False
    serialized = json.dumps(step)
    assert "DO_NOT_DUMP_RAW_WEB_SOURCE" not in serialized
    assert "token=secret" not in serialized
