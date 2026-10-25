"""Read-only image baseline report contracts; no real model required."""
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
        assert url == "http://127.0.0.1:8010/api/performance/observatory?limit=100"
        return {"media": {"recent_jobs": [
            {"id": first, "kind": "image", "status": "completed",
             "model": "qwen-image-edit", "total_ms": 10000, "queue_wait_ms": 150,
             "generation_ms": 9850, "prompt": "private user text",
             "provider_timing": {
                 "process_wall_ms": 5000, "process_spawn_ms": 10,
                 "first_output_ms": None, "fresh_process": True,
                 "tqdm_first_ms": 8100, "tqdm_first_step": 0,
                 "tqdm_complete_ms": 59000, "tqdm_window_ms": 50900,
                 "provider": "mflux", "low_ram": True, "mflux_cache_limit_gb": 4.0,
                 "steps": 20, "width": 1024, "height": 768,
                 "reference_count": 2, "guidance": 1.0,
                 "use_step_cache": False, "use_kv_cache": True,
                 "prompt": "secret"},
             "performance_timings": {"execution_ms": 5500, "resource_wait_ms": 50,
                                     "source_path": "/private/source.png"}},
            {"id": "c" * 24, "kind": "video", "status": "completed"},
            {"id": second, "kind": "image", "status": "completed",
             "model": "qwen-image-edit", "total_ms": 8000,
             "queue_wait_ms": 100, "generation_ms": 7900},
            {"id": "bad/path", "kind": "image", "status": "completed"},
            {"id": "d" * 24, "kind": "image", "status": "failed"},
        ]}}
    result = report.collect("http://127.0.0.1:8010", getter=getter)
    assert result["received_samples"] == 2
    assert result["completed_image_jobs"] == 2
    assert result["by_model"][0]["model"] == "qwen-image-edit"
    assert result["by_model"][0]["count"] == 2
    assert result["by_model"][0]["total_ms"]["median"] == 9000
    assert result["median_ms"]["total_ms"] == 9000
    assert result["median_ms"]["first_output_ms"] is None
    assert result["samples"][0]["fresh_process"] is True
    assert result["samples"][0]["process_spawn_ms"] == 10
    assert result["samples"][0]["provider"] == "mflux"
    assert result["samples"][0]["low_ram"] is True
    assert result["samples"][0]["tqdm_first_ms"] == 8100
    assert result["samples"][0]["tqdm_first_step"] == 0
    assert result["samples"][0]["tqdm_complete_ms"] == 59000
    assert result["samples"][0]["tqdm_window_ms"] == 50900
    assert result["median_ms"]["tqdm_window_ms"] == 50900
    assert result["samples"][0]["mflux_cache_limit_gb"] == 4.0
    assert result["samples"][0]["steps"] == 20
    assert result["samples"][0]["width"] == 1024
    assert result["samples"][0]["height"] == 768
    assert result["samples"][0]["reference_count"] == 2
    assert result["samples"][0]["guidance"] == 1.0
    assert result["samples"][0]["use_step_cache"] is False
    assert result["samples"][0]["use_kv_cache"] is True
    assert result["samples"][0]["execution_ms"] == 5500
    assert calls == ["http://127.0.0.1:8010/api/performance/observatory?limit=100"]
    assert "private user text" not in str(result)
    assert "secret" not in str(result)
    assert "/private/" not in str(result)
    assert first not in str(result) and second not in str(result)


def test_grouped_report_filters_details_by_exact_model_without_extra_requests():
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
        return {"media": {"recent_jobs": rows}}

    result = report.collect("http://127.0.0.1:8010", samples=2,
                            model="juggernaut-xl", getter=getter)
    assert result["selected_model"] == "juggernaut-xl"
    assert result["completed_image_jobs"] == 4
    assert result["received_samples"] == 2
    assert [row["model"] for row in result["samples"]] == ["juggernaut-xl"] * 2
    assert len(calls) == 1
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
    assert len(calls) == 2


def test_unknown_timing_is_not_zero():
    assert report.safe_ms(None) is None
    assert report.safe_ms(float("inf")) is None
    assert report.safe_ms(-1) is None
    assert report.safe_ms(True) is None
    assert report.safe_ms(0) == 0
    assert report.time_series([None, -1, float("nan"), float("inf"), True]) == {
        "count": 0, "median": None, "p95": None, "average": None}
    assert report.time_series([100, 300]) == {
        "count": 2, "median": 200, "p95": 290, "average": 200}


def test_juggernaut_phase_breakdown_is_visible_without_private_payload():
    def getter(_url):
        return {"media": {"recent_jobs": [{
            "id": "e" * 24, "kind": "image", "status": "completed",
            "model": "juggernaut-xl",
            "total_ms": 36300, "generation_ms": 36250, "queue_wait_ms": 50,
            "provider_timing": {
                "provider": "sdxl", "cold_model": True,
                "model_prepare_ms": 10000, "pipeline_setup_ms": 1000,
                "first_step_ms": 1700, "denoise_window_ms": 20100,
                "decode_finish_ms": 2800, "image_save_ms": 450,
                "worker_total_ms": 36050,
                "prompt": "never disclose me", "path": "/private/file.png",
            },
        }]}}
    result = report.collect("http://127.0.0.1:8010",
                            model="juggernaut-xl", getter=getter)
    row = result["samples"][0]
    assert row["sdxl_cold_model"] is True
    assert row["sdxl_model_prepare_ms"] == 10000
    assert row["sdxl_denoise_window_ms"] == 20100
    assert row["sdxl_decode_finish_ms"] == 2800
    assert result["median_ms"]["sdxl_model_prepare_ms"] == 10000
    assert "never disclose" not in str(result)
    assert "/private/" not in str(result)
