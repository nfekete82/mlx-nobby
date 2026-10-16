"""Unified-memory regression tests for SDXL and image model guards."""
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
    # No real worker was launched; release the temporary diagnostics.
    with mock.patch.object(providers, "terminate_process_tree"):
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


def test_process_guard_detects_system_pressure_not_only_process_rss():
    low = {**SAFE, "free_percent": 19.0}
    process = mock.Mock(pid=12345)
    with mock.patch.object(providers.sys, "platform", "darwin"), \
         mock.patch.object(runtime, "memory_budget_snapshot", side_effect=[SAFE, low]), \
         mock.patch.object(providers.subprocess, "run", return_value=mock.Mock(stdout="5000")):
        guard = providers.ImageProcessMemoryGuard()
        guard._last_system_probe = 0.0
        with pytest.raises(RuntimeError, match="RAM-Schutz"):
            guard.check(process)


def test_process_guard_detects_swap_spike_even_with_high_free_ram():
    swap_growth = {**SAFE, "swap_used_gb": SAFE["swap_used_gb"] + 0.75}
    process = mock.Mock(pid=12345)
    with mock.patch.object(providers.sys, "platform", "darwin"), \
         mock.patch.object(runtime, "memory_budget_snapshot", side_effect=[SAFE, swap_growth]), \
         mock.patch.object(providers.subprocess, "run", return_value=mock.Mock(stdout="5000")):
        guard = providers.ImageProcessMemoryGuard()
        guard._last_system_probe = 0.0
        with pytest.raises(RuntimeError, match="Swap"):
            guard.check(process)


def test_sdxl_worker_does_not_fallback_to_eager_mps_if_offload_unavailable():
    """Missing Accelerate is a hard failure, not permission to bypass the cap."""
    import io
    import json
    import sys
    import types
    import sdxl_worker

    class Pipeline:
        def __init__(self):
            self.scheduler = types.SimpleNamespace(config={})
        @classmethod
        def from_single_file(cls, *args, **kwargs):
            return cls()
        def to(self, *args, **kwargs):
            raise AssertionError("Unsafe eager MPS fallback")
        def enable_model_cpu_offload(self, **kwargs):
            raise ImportError("accelerate missing")

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "float16"
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True)
    )
    fake_torch.mps = types.SimpleNamespace(empty_cache=lambda: None)
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.StableDiffusionXLPipeline = Pipeline
    fake_diffusers.DPMSolverMultistepScheduler = mock.Mock()
    request = {
        "request_id": "guard-check",
        "checkpoint": "/local/checkpoint.safetensors",
        "config": "/local/config",
        "params": {"scheduler": "dpmpp-2m-karras"},
    }
    output = io.StringIO()
    with mock.patch.dict(sys.modules, {
        "torch": fake_torch, "diffusers": fake_diffusers
    }), mock.patch.object(sdxl_worker.sys, "stdin", io.StringIO(json.dumps(request) + "\n")), \
         mock.patch.object(sdxl_worker.sys, "stdout", output):
        sdxl_worker.main()
    event = json.loads(output.getvalue().strip())
    assert event["type"] == "error"
    assert "kein unsicherer Fallback" in event["message"]


def test_sdxl_oom_message_never_suggests_disabling_safety_limit():
    import io
    import json
    import sys
    import types
    import sdxl_worker

    class Pipeline:
        def __init__(self):
            self.scheduler = types.SimpleNamespace(config={})
        @classmethod
        def from_single_file(cls, *args, **kwargs):
            raise RuntimeError(
                "MPS backend out of memory (MPS allocated: 10.10 GiB). "
                "Use PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0 to disable upper limit"
            )

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "float16"
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: True)
    )
    fake_torch.mps = types.SimpleNamespace(empty_cache=lambda: None)
    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.StableDiffusionXLPipeline = Pipeline
    fake_diffusers.DPMSolverMultistepScheduler = mock.Mock()
    request = {
        "request_id": "oom-message",
        "checkpoint": "/local/checkpoint.safetensors",
        "config": "/local/config",
        "params": {"scheduler": "dpmpp-2m-karras"},
    }
    output = io.StringIO()
    with mock.patch.dict(sys.modules, {
        "torch": fake_torch, "diffusers": fake_diffusers
    }), mock.patch.object(sdxl_worker.sys, "stdin", io.StringIO(json.dumps(request) + "\n")), \
         mock.patch.object(sdxl_worker.sys, "stdout", output):
        sdxl_worker.main()
    event = json.loads(output.getvalue().strip())
    assert event["type"] == "error"
    assert "Sicheres MPS-Speicherlimit" in event["message"]
    assert "WATERMARK_RATIO=0.0" not in event["message"]
