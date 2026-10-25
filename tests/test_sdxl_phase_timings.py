"""Isolated monotonic timing and privacy contracts for SDXL."""
import json

import pytest

from sdxl_phase_timings import SDXLPhaseTimer
from agent import performance_observatory_routes as performance


def test_phase_timer_reports_measured_durations_and_no_private_data():
    clock = iter([100, 110, 115, 119, 145, 151, 153])
    timer = SDXLPhaseTimer(clock=lambda: next(clock))
    for phase in (
        "model_ready", "inference_started", "first_step",
        "last_step", "inference_finished", "saved",
    ):
        timer.mark(phase)
    result = timer.report(cold_model=True, steps=35,
                          width=1216, height=832, guidance=4.0)
    assert result == {
        "provider": "sdxl", "cold_model": True,
        "worker_total_ms": 53000.0, "model_prepare_ms": 10000.0,
        "pipeline_setup_ms": 5000.0, "first_step_ms": 4000.0,
        "denoise_window_ms": 26000.0, "decode_finish_ms": 6000.0,
        "image_save_ms": 2000.0,
        "steps": 35, "width": 1216, "height": 832, "guidance": 4.0,
    }
    serialized = json.dumps(result)
    assert "prompt" not in serialized and "source" not in serialized


def test_absent_phases_remain_null_and_extra_phase_rejected():
    clock = iter([100, 105])
    timer = SDXLPhaseTimer(clock=lambda: next(clock))
    timer.mark("model_ready")
    result = timer.report(cold_model=False, steps=20)
    assert result["model_prepare_ms"] == 5000.0
    assert result["denoise_window_ms"] is None
    assert result["worker_total_ms"] is None
    assert result["cold_model"] is False
    with pytest.raises(ValueError):
        timer.mark("private_prompt")


def test_observatory_sanitizes_sdxl_phases_and_blocks_private_fields():
    raw = {
        "id": "d" * 24, "kind": "image", "status": "completed",
        "model": "juggernaut-xl", "created_at": 100,
        "started_at": 101, "finished_at": 138,
        "provider_timing": {
            "provider": "sdxl", "cold_model": True,
            "model_prepare_ms": 12000.123,
            "pipeline_setup_ms": 400,
            "first_step_ms": 500,
            "denoise_window_ms": 20000,
            "decode_finish_ms": 3500,
            "image_save_ms": 200,
            "worker_total_ms": 36600,
            "steps": 35, "width": 1216, "height": 832,
            "guidance": 4.0,
            "prompt": "private text",
            "checkpoint": "/secret/checkpoint.safetensors",
            "another_number": 999999999,
        },
    }
    snapshot = performance.media_performance_snapshot({"jobs": [raw]}, limit=10)
    timing = snapshot["recent_jobs"][0]["provider_timing"]
    assert timing["provider"] == "sdxl"
    assert timing["model_prepare_ms"] == 12000.12
    assert timing["cold_model"] is True
    assert timing["steps"] == 35
    assert timing["decode_finish_ms"] == 3500
    assert "prompt" not in json.dumps(snapshot)
    assert "checkpoint" not in json.dumps(snapshot)
    assert "another_number" not in json.dumps(snapshot)
