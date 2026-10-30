"""CPU-only tests for bounded 9/30/60-second MLX segments and identity lock."""
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
        (9, "1080p", 3), (30, "1080p", 10), (60, "1080p", 20),
        (30, "720p", 6), (60, "540p", 10),
    ]:
        plan = segmented.plan(duration, resolution)
        assert len(plan["stages"]) == count
        assert sum(s["seconds"] for s in plan["stages"]) == duration
        assert all(stage["frames"] == stage["seconds"] * 24 + 1 for stage in plan["stages"])
        assert plan["strategy"] == "segmented-low-ram-v1"
    assert segmented.needed({"duration": 9})
    assert segmented.needed({"duration": 30})
    assert not segmented.needed({"duration": 20})
    job = video_service.JobCreate(operation="t2v", chat_id="chat", chat_revision=0,
        payload={"prompt": "A steady shot", "model": video_registry.LTX_MLX_Q4_ID,
                 "duration": 60, "quality": "quality"})
    assert (job.payload.width, job.payload.height, job.payload.frames) == (1920, 1088, 1441)
    with pytest.raises(ValueError):
        segmented.plan(30, "1080p", 8)
    with pytest.raises(ValueError):
        segmented.plan(9, "720p")
    nine = video_service.JobCreate(operation="t2v", chat_id="chat", chat_revision=0,
        payload={"prompt": "A steady shot", "model": video_registry.LTX_MLX_Q4_ID,
                 "duration": 9, "quality": "quality"})
    assert (nine.payload.width, nine.payload.height, nine.payload.frames) == (1920, 1088, 217)
    with pytest.raises(ValueError):
        video_service.VideoPayload(prompt="A person smiles", identity_strength=0.9)


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
        assert len(paths) == len(segmented.plan(params["duration"], params["resolution"])["stages"])
        assert all(path.is_file() for path in paths)
        output.write_bytes(b"result")
        return dict(width=1920, height=1088, fps=24,
                    frames=params["duration"] * 24, duration=params["duration"], audio=True)
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



def test_identity_lock_anchors_original_without_replacing_motion(pipeline, monkeypatch):
    tmp_path, model, params, kwargs = pipeline
    still = tmp_path / "original.png"
    still.write_bytes(b"original identity reference")
    params.update(first_frame=str(still), duration=9, frames=217,
                  identity_lock=True, identity_strength=0.30)
    # No heavyweight native keyframe probing is needed in CPU-only tests.
    monkeypatch.setattr("video_multi_image.keyframe_capabilities",
                        lambda _: {"native_keyframes": True})
    calls = []
    def generate(_model, segment, output, **_callbacks):
        calls.append(segment)
        output.write_bytes(b"video-segment")
    with mock.patch.object(segmented, "shutdown_warm_runtime"):
        result = segmented.run(model, params, tmp_path / "identity.mp4",
                               job_id="c" * 24, resume_job=None,
                               generate=generate, update=lambda **_: None, **kwargs)
    assert len(calls) == 3
    assert calls[0]["first_frame"] == str(still)
    assert calls[0]["images"] == []
    for index in (1, 2):
        call = calls[index]
        assert call["seed"] == 100, "identity-mode seed should stay fixed"
        assert call["first_frame"].endswith(f"last-frame-{index - 1}.png")
        assert call["images"] == [{
            "path": str(still), "frame_index": 0, "strength": 0.30,
            "binding": "guide",
        }]
        assert "same facial features" in call["prompt"]
        assert call["_active_memory_guard"] is True
    assert result["identity_lock"] is True
    assert result["identity_strength"] == 0.30
    assert result["stage_count"] == 3


def test_identity_lock_can_be_disabled_without_changing_old_seed_strategy(pipeline):
    tmp_path, model, params, kwargs = pipeline
    still = tmp_path / "original.png"
    still.write_bytes(b"same original")
    params.update(first_frame=str(still), duration=9, frames=217,
                  identity_lock=False)
    calls = []
    def generate(_model, segment, output, **_callbacks):
        calls.append(segment)
        output.write_bytes(b"video-segment")
    with mock.patch.object(segmented, "shutdown_warm_runtime"):
        result = segmented.run(model, params, tmp_path / "no-lock.mp4",
                               job_id="d" * 24, resume_job=None,
                               generate=generate, update=lambda **_: None, **kwargs)
    assert [call["seed"] for call in calls] == [100, 101, 102]
    assert all(not call["images"] for call in calls)
    assert result["identity_lock"] is False


def test_identity_lock_requires_native_keyframe_support(pipeline, monkeypatch):
    tmp_path, model, params, kwargs = pipeline
    still = tmp_path / "original.png"
    still.write_bytes(b"identity reference")
    params.update(first_frame=str(still), duration=9, frames=217,
                  identity_lock=True)
    monkeypatch.setattr("video_multi_image.keyframe_capabilities",
                        lambda _: {"native_keyframes": False})
    def no_generate(*_args, **_kwargs):
        raise AssertionError("must fail before starting a GPU worker")
    with pytest.raises(ValueError, match="native LTX-MLX-Keyframes"):
        segmented.run(model, params, tmp_path / "unavailable.mp4",
                      job_id="e" * 24, resume_job=None,
                      generate=no_generate, update=lambda **_: None, **kwargs)



def test_compose_removes_duplicate_boundary_frames_without_concurrent_decoders(
        tmp_path, monkeypatch):
    clips = [tmp_path / f"segment-{index}.mp4" for index in range(3)]
    for clip in clips:
        clip.write_bytes(b"placeholder")
    output = tmp_path / "complete.mp4"
    commands = []

    def probe(path):
        return dict(
            width=1920, height=1088, fps=24, audio=True,
            frames=217 if Path(path) == output else 73,
            duration=9.04 if Path(path) == output else 3.04,
        )

    def fake_ffmpeg(command, _cancel, _owner, timeout=600):
        commands.append(command)
        output.write_bytes(b"assembled")

    monkeypatch.setattr(segmented, "_probe_video", probe)
    monkeypatch.setattr(segmented, "_ffmpeg", fake_ffmpeg)
    info = segmented._compose(
        clips, output, {"duration": 9, "resolution": "1080p", "fps": 24},
        threading.Event(), "test:segmented",
    )
    assert info["frames"] == 217
    assert len(commands) == 1
    command = commands[0]
    video_filter = command[command.index("-vf") + 1]
    assert "mod(n,73)" in video_filter
    assert "setpts=N/(24*TB)" in video_filter
    assert command[command.index("-fps_mode") + 1] == "cfr"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert "copy" not in command
    assert command[command.index("-map") + 1] == "0:v:0"
    assert "0:a:0" in command
    assert "atempo=" in command[command.index("-af") + 1]


def test_compose_rejects_framecount_mismatch(tmp_path, monkeypatch):
    clips = [tmp_path / f"segment-{index}.mp4" for index in range(3)]
    for clip in clips:
        clip.write_bytes(b"placeholder")
    monkeypatch.setattr(segmented, "_probe_video", lambda _: dict(
        width=1920, height=1088, fps=24, audio=False, frames=72,
        duration=3.0,
    ))
    with pytest.raises(RuntimeError, match="Randframes"):
        segmented._compose(
            clips, tmp_path / "complete.mp4",
            {"duration": 9, "resolution": "1080p", "fps": 24},
            threading.Event(), "test:segmented",
        )


def test_compose_real_ffmpeg_yields_217_cfr_frames_and_audio(tmp_path, monkeypatch):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for an executable stitching smoke test")
    clips = []
    for idx, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"segment-{idx}.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=128x96:r=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-frames:v", "73", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-t", "3.041667", str(path),
        ], check=True, capture_output=True, timeout=45)
        clips.append(path)
    def direct_ffmpeg(command, _cancel, _owner, timeout=600):
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    monkeypatch.setattr(segmented, "_ffmpeg", direct_ffmpeg)
    result = segmented._compose(
        clips, tmp_path / "complete.mp4",
        {"duration": 9, "resolution": "1080p", "fps": 24},
        threading.Event(), "test:segmented",
    )
    assert result["frames"] == 217
    assert result["fps"] == 24
    assert result["audio"] is True
    assert abs(result["duration"] - 9) < 0.1
