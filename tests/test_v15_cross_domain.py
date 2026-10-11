"""Cross-domain live benchmark must never imply semantic quality from transport success."""
import csv
import json

import pytest

from agent.v15_cross_domain import (
    case_technical, create_review_csv, run_suite, score_reviews, suite_cases,
    technical_summary, REVIEW_COLUMNS, REVIEW_DIMENSIONS,
)


def fake_response(question, *, supported=4, elapsed=2000):
    return {
        "id": "live-001", "question": question, "elapsed_ms": elapsed,
        "review_status": "pending", "response": {
            "status": "completed", "answer": "Example result.",
            "steps": [
                {"action": "search_web", "status": "completed",
                 "result": {"provider": "SearXNG",
                            "results": [{"url": "https://example.org/source"}]}},
                {"action": "fetch_url", "status": "completed",
                 "result": {"ok": True, "url": "https://example.org/source",
                            "text": "A sourced but possibly irrelevant piece of text." * 5}},
            ],
            "evidence": {"claims": [{"status": "supported"}] * supported,
                         "verified_supported_count": supported},
            "performance": {"events": [
                {"action": "provider.complete", "purpose": "agent.plan",
                 "duration_ms": 600, "prompt_tokens": 100},
                {"action": "provider.complete", "purpose": "agent.verify",
                 "duration_ms": 400, "prompt_tokens": 250},
            ]},
        },
    }


def test_out_of_sample_suite_is_multidomain_and_avoids_the_tuned_apple_case():
    cases = suite_cases()
    assert len(cases) >= 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert len({case["category"] for case in cases}) >= 8
    assert all(case["review_criteria"] for case in cases)
    assert all("Welche aktuellen iPhone-Modelle" not in case["question"] for case in cases)


def test_four_supported_claims_do_not_trigger_quality_pass():
    row = fake_response("What is the answer?")
    technical = case_technical(row)
    assert technical["completed"] is True
    assert technical["verified_supported_count"] == 4
    assert technical["loaded_source_count"] == 1
    assert technical["search_actions"] == technical["fetch_actions"] == 1
    assert technical["search_providers"] == ["SearXNG"]
    assert technical["model_calls"] == 2
    assert technical["model_ms"] == 1000
    assert technical["unattributed_ms"] == 1000
    assert technical["model_call_ms_by_purpose"] == {
        "agent.plan": 600, "agent.verify": 400,
    }
    summary = technical_summary([row])
    assert summary["quality_status"] == "unreviewed"
    assert summary["completed"] == 1
    assert summary["model_time_fraction"] == .5
    assert summary["latency_p95_nearest_rank_ms"] == 2000


def test_safe_abstention_and_transport_error_are_not_auto_scored_as_failure():
    absent = fake_response("Unknown device", supported=0, elapsed=3000)
    transport_error = {"id": "CD99", "elapsed_ms": 3500, "error": "timeout",
                       "review_status": "error"}
    report = technical_summary([absent, transport_error])
    assert report["completed"] == 1
    assert report["errors"] == 1
    assert report["zero_supported_cases"] == 2
    assert report["quality_status"] == "unreviewed"
    assert report["latency_median_ms"] == 3250
    assert report["latency_p95_nearest_rank_ms"] == 3500


def test_run_writes_raw_capture_metrics_and_blank_review(tmp_path):
    cases = suite_cases()[:2]
    seen = []

    def fake_capture(questions, endpoint, timeout):
        seen.append((questions, endpoint, timeout))
        return [fake_response(questions[0])]

    directory = tmp_path / "eval"
    summary = run_suite(endpoint="http://127.0.0.1:8010/api/agent/run",
                        output_dir=directory, limit=2, timeout=100,
                        capture_fn=fake_capture, cases=cases)
    assert len(seen) == 2
    assert summary["total"] == 2
    assert summary["completed"] == 2
    assert [json.loads(line)["id"] for line in (directory / "capture.jsonl").read_text().splitlines()] == [
        cases[0]["id"], cases[1]["id"],
    ]
    with (directory / "human_review.csv").open(newline="", encoding="utf-8") as handle:
        reviews = list(csv.DictReader(handle))
    assert len(reviews) == 2
    assert all(not row["relevance"] and not row["accuracy"] for row in reviews)
    assert json.loads((directory / "technical_summary.json").read_text())["quality_status"] == "unreviewed"
    with pytest.raises(FileExistsError):
        run_suite(output_dir=directory, capture_fn=fake_capture, cases=cases)


def test_invalid_remote_endpoint_never_invokes_capture(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        run_suite(endpoint="https://remote.example/api/agent/run",
                  output_dir=tmp_path / "never", cases=suite_cases()[:1],
                  capture_fn=lambda *args, **kwargs: (_ for _ in ()).throw(
                      AssertionError("No remote requests permitted")))


def test_review_scoring_requires_every_dimension_and_all_cases(tmp_path):
    path = tmp_path / "reviews.csv"
    cases = suite_cases()[:2]
    create_review_csv(cases, path)
    result = score_reviews(path, [case["id"] for case in cases])
    assert result["reviewed"] == 0
    assert result["pending"] == [case["id"] for case in cases]
    assert result["fully_acceptable"] is False

    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    rows[0].update({col: "2" for col in REVIEW_DIMENSIONS})
    rows[1].update({col: "2" for col in REVIEW_DIMENSIONS})
    rows[1]["citations"] = "1"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    complete = score_reviews(path, [case["id"] for case in cases])
    assert complete["reviewed"] == 2
    assert complete["complete"] is True
    assert complete["fully_acceptable"] is False
    assert complete["scores"]["citations"] == 1.5


def test_incomplete_and_forged_review_rows_fail_closed(tmp_path):
    path = tmp_path / "reviews.csv"
    cases = suite_cases()[:1]
    create_review_csv(cases, path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["relevance"] = "2"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="ALL five"):
        score_reviews(path, [cases[0]["id"]])
    rows[0]["relevance"] = "0"
    rows[0]["id"] = "forged"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="match"):
        score_reviews(path, [cases[0]["id"]])
