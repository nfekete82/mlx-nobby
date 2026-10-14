"""The read-only image timing report never triggers generation or exposes prompts."""
import argparse
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/report-image-edit-baseline.py"
spec = importlib.util.spec_from_file_location("image_edit_baseline_report", MODULE_PATH)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def test_loopback_validation():
    assert report.loopback_origin("http://127.0.0.1:8010/") == "http://127.0.0.1:8010"
    for url in ("https://127.0.0.1:8010", "http://example.com:8010",
                "http://127.0.0.1:8010/other", "http://u:p@localhost:8010"):
        with pytest.raises(argparse.ArgumentTypeError):
            report.loopback_origin(url)


def test_report_collects_only_completed_image_jobs_and_omits_private_fields():
    first, second = "a" * 24, "b" * 24
    calls = []
    def getter(url):
        calls.append(url)
        if url.endswith("/api/performance/observatory?limit=100"):
            return {"media": {"recent_jobs": [
                {"id": first, "kind": "image", "status": "completed",
                 "model": "qwen-image-edit", "total_ms": 10000, "queue_wait_ms": 150,
                 "generation_ms": 9850, "prompt": "private user text"},
                {"id": "c" * 24, "kind": "video", "status": "completed"},
                {"id": second, "kind": "image", "status": "completed",
                 "model": "qwen-image-edit", "total_ms": 8000, "queue_wait_ms": 100,
                 "generation_ms": 7900},
                {"id": "bad/path", "kind": "image", "status": "completed"},
                {"id": "d" * 24, "kind": "image", "status": "failed"},
            ]}}
        identifier = url.rsplit("/", 1)[-1]
        return {"data": {"job": {
            "id": identifier, "kind": "image",
            "provider_timing": {"process_wall_ms": 5000, "process_spawn_ms": 10,
                                "first_output_ms": None, "fresh_process": True,
                                "prompt": "secret"},
            "performance_timings": {"execution_ms": 5500, "resource_wait_ms": 50},
            "source_path": "/private/source.png",
        }}}
    result = report.collect("http://127.0.0.1:8010", getter=getter)
    assert result["received_samples"] == 2
    assert result["completed_image_jobs"] == 2
    assert result["by_model"][0]["model"] == "qwen-image-edit"
    assert result["by_model"][0]["count"] == 2
    assert result["by_model"][0]["total_ms"]["median"] == 9000
    assert result["median_ms"]["total_ms"] == 9000
    assert result["median_ms"]["first_output_ms"] is None
    assert result["samples"][0]["fresh_process"] is True
    assert len(calls) == 3
    assert "private user text" not in str(result)
    assert "secret" not in str(result)
    assert "/private/" not in str(result)
    assert first not in str(result) and second not in str(result)


def test_report_rejects_swapped_job_identity():
    job_id = "b" * 24
    def getter(url):
        if "observatory" in url:
            return {"media": {"recent_jobs": [{"id": job_id, "kind": "image",
                                                "status": "completed"}]}}
        return {"data": {"job": {"id": "a" * 24, "kind": "image"}}}
    with pytest.raises(ValueError, match="identity"):
        report.collect("http://localhost:8010", getter=getter)


def test_unknown_timing_is_not_zero():
    assert report.safe_ms(None) is None
    assert report.safe_ms(float("inf")) is None
    assert report.safe_ms(-1) is None
    assert report.safe_ms(True) is None
    assert report.safe_ms(0) == 0


def test_grouped_report_filters_details_by_exact_model_without_extra_job_fetches():
    rows = [
        {"id": "a" * 24, "kind": "image", "status": "completed",
         "model": "juggernaut-xl", "total_ms": 10000,
         "generation_ms": 9960, "queue_wait_ms": 40},
        {"id": "b" * 24, "kind": "image", "status": "completed",
         "model": "mflux-osaurus-qwen-image-2.1-edit", "total_ms": 50000,
         "generation_ms": 49990, "queue_wait_ms": 10},
        {"id": "c" * 24, "kind": "image", "status": "completed",
         "model": "juggernaut-xl", "total_ms": 20000,
         "generation_ms": 19920, "queue_wait_ms": 80},
        {"id": "d" * 24, "kind": "image", "status": "completed",
         "model": "juggernaut-xl", "total_ms": 30000,
         "generation_ms": 29880, "queue_wait_ms": 120},
    ]
    calls = []
    def getter(url):
        calls.append(url)
        if url.endswith("/api/performance/observatory?limit=100"):
            return {"media": {"recent_jobs": rows}}
        return {"data": {"job": {"id": url.rsplit("/", 1)[-1], "kind": "image"}}}

    result = report.collect("http://127.0.0.1:8010", samples=2,
                            model="juggernaut-xl", getter=getter)
    assert result["selected_model"] == "juggernaut-xl"
    assert result["completed_image_jobs"] == 4
    assert result["received_samples"] == 2
    assert [row["model"] for row in result["samples"]] == ["juggernaut-xl"] * 2
    assert len(calls) == 3  # Observatory + two selected job details
    assert all("b" * 24 not in url for url in calls)
    assert [group["count"] for group in result["by_model"]] == [3, 1]
    juggernaut = result["by_model"][0]
    assert juggernaut["model"] == "juggernaut-xl"
    assert juggernaut["total_ms"]["median"] == 20000
    assert juggernaut["total_ms"]["p95"] == 29000
    assert juggernaut["queue_wait_ms"]["median"] == 80

    absent = report.collect("http://127.0.0.1:8010", samples=3,
                            model="mflux-qwen-image-edit-2511", getter=getter)
    assert absent["received_samples"] == 0
    assert absent["completed_image_jobs"] == 4
    assert absent["by_model"] == result["by_model"]


def test_grouped_series_does_not_turn_missing_or_invalid_values_into_zero():
    summary = report.time_series([None, -1, float("nan"), float("inf"), True])
    assert summary == {"count": 0, "median": None, "p95": None, "average": None}
    assert report.time_series([100, 300]) == {
        "count": 2, "median": 200, "p95": 290, "average": 200}
