"""Unified-memory regression tests for SDXL and image model guards."""
import os
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

import image_providers as providers
import image_service_pipeline as pipeline
import runtime_coordinator as runtime


SAFE = {
    "pressure": "normal",
    "free_percent": 78.0,
    "total_gb": 48.0,
    "used_estimate_gb": 10.56,
    "headroom_gb": 31.4,
    "swap_used_gb": 15.0,
}


def test_active_guard_stops_at_20_percent_free_even_before_admission_ceiling():
    with pytest.raises(RuntimeError, match="RAM-Schutz"):
        runtime.ensure_active_memory_safe({**SAFE, "free_percent": 19.9})


def test_active_guard_blocks_swap_growth_not_old_swap():
    runtime.ensure_active_memory_safe(SAFE, baseline_swap_gb=30.0)
    with pytest.raises(RuntimeError, match="Swap"):
        runtime.ensure_active_memory_safe(
            {**SAFE, "swap_used_gb": 15.8}, baseline_swap_gb=15.0
        )


def test_active_guard_fails_closed_on_missing_or_invalid_memory_probe():
    for snapshot in (None, {}, {**SAFE, "free_percent": None}):
        with pytest.raises(RuntimeError, match="RAM-Schutz"):
            runtime.ensure_active_memory_safe(snapshot)


def test_worker_mps_watermarks_override_unsafe_inherited_environment(tmp_path):
    manager = providers.SDXLWorkerManager(worker_path=tmp_path / "fake.py")
    process = mock.Mock()
    process.poll.return_value = None
    process.pid = 12345
    with mock.patch.object(providers.subprocess, "Popen", return_value=process) as spawn:
        manager._start_locked({
            "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0",
            "PYTORCH_MPS_LOW_WATERMARK_RATIO": "0",
        })
    env = spawn.call_args.kwargs["env"]
    assert float(env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"]) <= 0.55
    assert 0 < float(env["PYTORCH_MPS_LOW_WATERMARK_RATIO"]) < float(env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"])
    # No real worker was launched.
    manager._process = None
    manager.close()


def test_image_runtime_can_force_chat_unload_when_initial_pressure_is_normal():
    commands = []
    def requester(method, url, payload=None, timeout=10):
        return {"status": "ready", "loaded": False, "active_generation": False}
    with tempfile.TemporaryDirectory() as directory:
        with runtime.image_runtime(
            threading.Event(),
            requester=requester,
            chat_loaded=lambda: True,
            chat_command=commands.append,
            lock_path=Path(directory) / "runtime.lock",
            memory_snapshot=lambda: SAFE.copy(),
            force_chat_unload=True,
        ) as preflight:
            assert commands == ["stop"]
            assert preflight["chat_released"] is True
        assert commands == ["stop", "start"]


def test_sdxl_speculative_prewarm_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MLX_IMAGE_SDXL_PREWARM", raising=False)
    monkeypatch.setattr(pipeline, "_route_generation_model",
                        lambda *_: {"id": "lustify-endgame-sdxl", "provider": "sdxl"})
    result = pipeline.prewarm(pipeline.PrewarmRequest(model="lustify-endgame-sdxl"))
    assert result["started"] is False
    assert result["warm"] is False
    assert result["reason"] == "sdxl-prewarm-disabled-for-memory-safety"
