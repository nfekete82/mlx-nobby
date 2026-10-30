"""CPU-only contracts for checkpointed LTX long-video generation."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

import video_long
import video_providers
import video_registry
import video_service


def _request(**kwargs):
    payload = dict(model=video_registry.LTX_MLX_Q4_ID, prompt="Slow tracking shot",
                   quality="quality", duration=30, long_video=True)
    payload.update(kwargs)
    return video_service.JobCreate(operation="t2v", chat_id="chat", chat_revision=0,
                                   payload=payload)


def test_duration_validation_and_frames():
    assert len(video_long.segment_plan(30, "1080p")) == 10
    assert len(video_long.segment_plan(60, "1080p")) == 20
    assert len(video_long.segment_plan(30, "720p")) == 6
    assert len(video_long.segment_plan(60, "540p")) == 10
    request = _request()
    assert request.payload.frames == 721
    assert (request.payload.width, request.payload.height) == (1920, 1088)
    assert request.payload.duration == 30
    assert request.payload.long_video
    assert _request(duration=60).payload.frames == 1441
    with pytest.raises(ValidationError):
        _request(long_video=False)
    with pytest.raises(ValidationError):
        _request(duration=25)
    with pytest.raises(ValidationError):
        _request(quality="preview")
    with pytest.raises(ValidationError):
        _request(model=video_registry.LTX_ID)


def test_long_video_allows_resume_only_in_checkpoint_mode():
    assert _request(resume_from="a" * 24).payload.resume_from == "a" * 24
    with pytest.raises(ValidationError):
        _request(resume_from="a" * 24, long_video=False)


def test_provider_only_accepts_generated_checkpoint_images(tmp_path, monkeypatch):
    root = tmp_path / "segments"
    monkeypatch.setattr(video_providers, "VIDEO_SEGMENTS_ROOT", root)
    directory = root / ("a" * 24)
    directory.mkdir(parents=True)
    good = directory / "last-frame-3.png"
    good.write_bytes(b"png")
    assert video_providers.validate_first_frame(str(good)) == good.resolve()
    for name in ["arbitrary.png", "last-frame-3.txt"]:
        bad = directory / name
        bad.write_bytes(b"png")
        with pytest.raises(ValueError):
            video_providers.validate_first_frame(str(bad))
    elsewhere = tmp_path / "elsewhere" / "last-frame-3.png"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"png")
    with pytest.raises(ValueError):
        video_providers.validate_first_frame(str(elsewhere))


def test_failed_long_video_resumes_from_completed_checkpoint(tmp_path, monkeypatch):
    state = {"segments": []}
    original_job = "a" * 24
    new_job = "b" * 24
    checkpoint = tmp_path / "checkpoints"
    resolution = dict(width=1920, height=1088, fps=24, audio=True, duration=3.0)

    def probe(_):
        return dict(resolution)

    def last_frame(_clip, image):
        image.write_bytes(b"reference frame")

    def concat(paths, output, params):
        assert len(paths) == 10
        assert params["duration"] == 30
        output.write_bytes(b"video")
        return dict(resolution, duration=30.0)

    def memory():
        return {"free_percent": 55.0, "pressure": "normal", "swap_used_gb": 0}

    monkeypatch.setattr(video_long, "_probe_video", probe)
    monkeypatch.setattr(video_long, "_last_frame", last_frame)
    monkeypatch.setattr(video_long, "_concat_segments", concat)
    monkeypatch.setattr(video_long.runtime_coordinator, "memory_budget_snapshot", memory)

    params = dict(prompt="Slow camera shot", resolution="1080p", duration=30,
                  width=1920, height=1088, fps=24, seed=23, quality="quality",
                  profile="standard", long_video=True, first_frame=None)
    calls = []
    def generate(_model, segment, path, **_kwargs):
        calls.append((segment["duration"], segment["frames"], segment["seed"],
                      segment.get("first_frame")))
        if len(calls) == 3:
            raise RuntimeError("simulated worker memory failure")
        path.write_bytes(b"video")

    def update(**kwargs):
        state.update(kwargs)

    callbacks = dict(generate=generate, cancel_event=threading.Event(),
                     response_callback=lambda _: None,
                     progress_callback=lambda _: None,
                     phase_callback=lambda _: None, update=update)

    with mock.patch.object(video_long, "shutdown_warm_runtime") as shutdown:
        with pytest.raises(RuntimeError, match="simulated worker"):
            video_long.generate_long_video(
                {"provider": "ltx-mlx"}, params, tmp_path / "bad.mp4",
                job_id=original_job, checkpoints=checkpoint,
                resume_job=None, **callbacks)
        assert shutdown.call_count == 3
    assert len(state["segments"]) == 2
    assert calls[1][3].endswith("last-frame-0.png")
    assert calls[0][:3] == (3, 73, 23)
    resumed = []
    def restored(_model, segment, path, **_kwargs):
        resumed.append(segment["seed"])
        path.write_bytes(b"video")

    with mock.patch.object(video_long, "shutdown_warm_runtime") as shutdown:
        result = video_long.generate_long_video(
            {"provider": "ltx-mlx"}, params, tmp_path / "done.mp4",
            job_id=new_job, checkpoints=checkpoint,
            resume_job={"id": original_job, "segments": state["segments"]},
            **{**callbacks, "generate": restored})
        assert shutdown.call_count == 8
    assert resumed == list(range(25, 33))
    assert result["segment_count"] == 10
    assert result["long_video"] is True
    assert result["segments"][0]["reused"] is True
    assert result["segments"][1]["reused"] is True
    assert not (checkpoint / new_job).exists()
    assert (checkpoint / original_job / "segment-0.mp4").is_file()
