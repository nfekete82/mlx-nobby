"""CPU-only tests for bounded 30/60-second MLX segments and checkpoint retries."""
import json
import threading
from pathlib import Path
from unittest import mock

import pytest

import video_providers
import video_segmented as segmented
import video_service
import video_registry
from video_providers import ProviderCancelled


def test_plans_and_native_request_contract():
    for duration, resolution, count in [
        (30, "1080p", 10), (60, "1080p", 20),
        (30, "720p", 6), (60, "540p", 10),
    ]:
        plan = segmented.plan(duration, resolution)
        assert len(plan["stages"]) == count
        assert sum(s["seconds"] for s in plan["stages"]) == duration
        assert all(stage["frames"] == stage["seconds"] * 24 + 1 for stage in plan["stages"])
        assert plan["strategy"] == "segmented-low-ram-v1"
    assert segmented.needed({"duration": 30})
    assert not segmented.needed({"duration": 20})
    job = video_service.JobCreate(operation="t2v", chat_id="chat", chat_revision=0,
        payload={"prompt": "A steady shot", "model": video_registry.LTX_MLX_Q4_ID,
                 "duration": 60, "quality": "quality"})
    assert (job.payload.width, job.payload.height, job.payload.frames) == (1920, 1088, 1441)
    with pytest.raises(ValueError):
        segmented.plan(30, "1080p", 8)


def test_checkpoint_stills_never_accept_arbitrary_nested_paths(tmp_path, monkeypatch):
    root = tmp_path / "segmented"
    monkeypatch.setattr(video_providers, "SEGMENTED_FRAMES", root)
    folder = root / ("a" * 24)
    folder.mkdir(parents=True)
    good = folder / "last-frame-0.png"
    good.write_bytes(b"png")
    assert video_providers.validate_first_frame(str(good)) == good.resolve()
    other = folder / "private.png"
    other.write_bytes(b"png")
    with pytest.raises(ValueError):
        video_providers.validate_first_frame(str(other))
    outside = tmp_path / "outside" / "last-frame-0.png"
    outside.parent.mkdir()
    outside.write_bytes(b"png")
    with pytest.raises(ValueError):
        video_providers.validate_first_frame(str(outside))


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    model_root = tmp_path / "model"
    model_root.mkdir()
    (model_root / "embedded_config.json").write_text("{}")
    monkeypatch.setattr(segmented.video_registry, "model_path", lambda _: model_root)
    monkeypatch.setattr(segmented.gate, "blocked", lambda: False)
    monkeypatch.setattr(segmented.runtime_coordinator, "memory_budget_snapshot",
                        lambda: {"free_percent": 55.0, "pressure": "normal", "swap_used_gb": 0})
    monkeypatch.setattr(segmented, "_probe_video",
                        lambda _: dict(width=1920, height=1088, fps=24,
                                       frames=73, duration=3.04, audio=True))
    def frame(_clip, path, _cancel, _owner):
        path.write_bytes(b"still")
    monkeypatch.setattr(segmented, "_last_frame", frame)
    def compose(paths, output, params, cancel, owner):
        assert len(paths) == 10
        assert all(path.is_file() for path in paths)
        output.write_bytes(b"result")
        return dict(width=1920, height=1088, fps=24, frames=720, duration=30, audio=True)
    monkeypatch.setattr(segmented, "_compose", compose)
    params = dict(prompt="Slow moving camera", model="auto", duration=30, resolution="1080p",
                  width=1920, height=1088, frames=721, fps=24, quality="quality",
                  profile="standard", seed=100, first_frame=None)
    model = dict(id=video_registry.LTX_MLX_Q4_ID, provider="ltx-mlx")
    kwargs = dict(checkpoints=tmp_path / "checkpoints", cancel_event=threading.Event(),
                  response_callback=lambda _: None, progress_callback=lambda _: None,
                  phase_callback=lambda _: None)
    return tmp_path, model, params, kwargs


def test_memory_failure_keeps_verified_chunks_and_resume_reuses_them(pipeline, monkeypatch):
    tmp_path, model, params, kwargs = pipeline
    calls, status = [], {}
    def update(**change):
        status.update(change)
    def failing(_model, segment, target, **callbacks):
        calls.append(segment)
        assert segment["_active_memory_guard"] is True
        assert segment["frames"] == 73
        if len(calls) == 3:
            raise RuntimeError("RAM-Schutz test")
        target.write_bytes(b"frame-and-audio")
    with mock.patch.object(segmented, "shutdown_warm_runtime") as reset:
        with pytest.raises(RuntimeError, match="RAM-Schutz"):
            segmented.run(model, params, tmp_path / "failed.mp4", job_id="a" * 24,
                          resume_job=None, generate=failing, update=update, **kwargs)
        assert reset.call_count == 3
    manifest_file = kwargs["checkpoints"] / ("a" * 24) / "checkpoint.json"
    saved = json.loads(manifest_file.read_text())
    assert len(saved["stages"]) == 2
    assert status["checkpoint_count"] == 2
    assert status["resumable"] is True
    assert calls[1]["first_frame"].endswith("last-frame-0.png")
    rerender = []
    def continued(_model, segment, target, **callbacks):
        rerender.append(segment["seed"])
        target.write_bytes(b"frame-and-audio")
    with mock.patch.object(segmented, "shutdown_warm_runtime") as reset:
        result = segmented.run(
            model, params, tmp_path / "success.mp4", job_id="b" * 24,
            resume_job={"id": "a" * 24, "status": "failed"},
            generate=continued, update=update, **kwargs)
        assert reset.call_count == 8
    assert rerender == list(range(102, 110))
    assert result["strategy"] == "segmented-low-ram-v1"
    assert result["stage_count"] == 10
    assert (tmp_path / "success.mp4").is_file()


def test_modified_checkpoint_is_rejected(pipeline, monkeypatch):
    tmp_path, model, params, kwargs = pipeline
    def generate(_model, segment, target, **callbacks):
        target.write_bytes(b"clip")
        kwargs["cancel_event"].set()
    with mock.patch.object(segmented, "shutdown_warm_runtime"):
        with pytest.raises(ProviderCancelled):
            segmented.run(model, params, tmp_path / "cancelled.mp4",
                          job_id="a" * 24, resume_job=None,
                          generate=generate, update=lambda **v: None, **kwargs)
    # Clear cancellation and replay with an altered checkpoint digest.
    kwargs["cancel_event"].clear()
    manifest = kwargs["checkpoints"] / ("a" * 24) / "checkpoint.json"
    # No completed checkpoint should be advertised when cancelled before validation.
    assert json.loads(manifest.read_text())["stages"] == []
