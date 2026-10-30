"""CPU-only rolling LTX time-window tests; small FFmpeg smoke if installed."""
import json
import shutil
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest

import video_rolling
import video_providers
import video_service


def test_opt_in_is_strict_and_existing_segment_mode_is_unchanged():
    assert not video_rolling.needed({"duration": 10, "resolution": "540p"})
    assert video_rolling.needed({"continuation_mode": "rolling"})
    planner = video_rolling.plan(10, "540p")
    assert planner["strategy"] == video_rolling.STRATEGY
    assert [stage["frames"] for stage in planner["stages"]] == [145, 48, 48]
    assert [stage["confirmed_duration"] for stage in planner["stages"]] == [6, 8, 10]
    assert planner["context_frames"] == 25
    assert planner["frames"] == 241
    hd = video_rolling.plan(10, "720p")
    assert hd["resolution"] == "720p"
    assert hd["context_frames"] == 25
    assert [stage["frames"] for stage in hd["stages"]] == [145, 48, 48]
    for resolution, expected in (
        ("540p", ((1024, 576), (576, 1024))),
        ("720p", ((1280, 704), (704, 1280))),
    ):
        for width, height in expected:
            video_rolling._validate_canvas({
                "resolution": resolution, "width": width, "height": height,
            })
    with pytest.raises(ValueError, match="Profilauflösung"):
        video_rolling._validate_canvas({
            "resolution": "720p", "width": 1024, "height": 576,
        })
    with pytest.raises(ValueError):
        video_rolling.plan(10, "1080p")
    with pytest.raises(ValueError):
        video_rolling.plan(20, "540p")
    with pytest.raises(ValueError):
        video_rolling.plan(10, "540p", 8)


def test_service_strict_mode_requires_540p_ten_seconds_and_single_video(monkeypatch):
    request = video_service.JobCreate(
        operation="t2v", chat_id="test", chat_revision=0,
        payload={"prompt": "The woman smiles naturally", "quality": "fast",
                 "duration": 10, "continuation_mode": "rolling"})
    assert request.payload.resolution == "540p"
    assert request.payload.width == 1024 and request.payload.height == 576
    assert request.payload.frames == 241
    assert request.payload.continuation_mode == "rolling"
    hd_request = video_service.JobCreate(
        operation="t2v", chat_id="test", chat_revision=0,
        payload={"prompt": "The woman smiles", "quality": "standard",
                 "duration": 10, "continuation_mode": "rolling",
                 "aspect_ratio": "9:16"})
    assert hd_request.payload.resolution == "720p"
    assert (hd_request.payload.width, hd_request.payload.height) == (704, 1280)
    with mock.patch.object(video_service, "validate_first_frame",
                           return_value=Path("/managed/portrait.png")), \
         mock.patch.object(video_service, "i2v_source_size",
                           return_value=(720, 1200)):
        portrait = video_service.JobCreate(
            operation="i2v", chat_id="test", chat_revision=0,
            payload={"prompt": "A portrait animation", "quality": "standard",
                     "duration": 10, "first_frame": "/managed/portrait.png",
                     "continuation_mode": "rolling", "aspect_ratio": "9:16"})
    assert (portrait.payload.width, portrait.payload.height) == (704, 1280)
    assert portrait.payload.resize_mode == "contain"
    with pytest.raises(ValueError):
        video_service.JobCreate(
            operation="t2v", chat_id="test", chat_revision=0,
            payload={"prompt": "The woman smiles", "quality": "quality",
                     "duration": 10, "continuation_mode": "rolling"})
    with pytest.raises(ValueError):
        video_service.JobCreate(
            operation="t2v", chat_id="test", chat_revision=0,
            payload={"prompt": "The woman smiles", "quality": "fast",
                     "duration": 20, "continuation_mode": "rolling"})


def test_chat_video_options_reach_native_rolling_request():
    from agent import app as agent_app
    from backend.media_intent import decide_media_intent
    prompt = ("Erstelle ein 10-Sekunden-Video mit Rolling-Window-Test: "
              "The person slowly turns their head and smiles naturally.")
    assert decide_media_intent(prompt, has_image=True).target == "video"
    request = agent_app.ChatActionRequest(
        prompt=prompt, quality="fast", video_options={
            "duration": 10, "continuation_mode": "rolling",
        },
    )
    with mock.patch.object(agent_app, "compile_video_prompt",
                           return_value="The person slowly turns their head and smiles naturally."):
        payload = agent_app._video_payload(request, "t2v")
    assert payload["continuation_mode"] == "rolling"
    assert payload["duration"] == 10
    assert payload["quality"] == "fast"


def test_tail_refuses_short_source_before_ffmpeg(tmp_path):
    clip = tmp_path / "short.mp4"
    clip.write_bytes(b"small")
    with mock.patch.object(video_rolling, "_probe_video", return_value={
        "frames": 24, "fps": 24, "width": 128, "height": 64,
        "duration": 1, "audio": True,
    }), mock.patch.object(video_rolling, "_ffmpeg") as f:
        with pytest.raises(ValueError, match="Zu wenig"):
            video_rolling._clip_frames(
                clip, tmp_path / "context.mp4", start=0, count=25,
                cancel=threading.Event(), owner="test")
        f.assert_not_called()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required for executable rolling smoke")
@pytest.mark.parametrize("with_photo", [False, True])
def test_rolling_extend_uses_only_25_context_frames_and_outputs_241(tmp_path, monkeypatch, with_photo):
    monkeypatch.setattr(video_providers, "FFPROBE", shutil.which("ffprobe"))
    monkeypatch.setattr(video_rolling, "FFMPEG", shutil.which("ffmpeg"))

    root = tmp_path / "model"
    root.mkdir()
    (root / "embedded_config.json").write_text("{}")
    monkeypatch.setattr(video_rolling.video_registry, "model_path", lambda _: root)
    monkeypatch.setattr(video_rolling.video_long, "runtime_version", lambda: "known-runtime")
    # The FFmpeg integration test uses 128x64 for speed; separate tests above
    # verify all four real 540p/720p landscape and portrait dimensions.
    monkeypatch.setattr(video_rolling, "_validate_canvas", lambda _: None)
    monkeypatch.setattr(video_rolling.gate, "blocked", lambda: False)
    monkeypatch.setattr(video_rolling, "shutdown_warm_runtime", lambda: None)
    monkeypatch.setattr(video_rolling.runtime_coordinator, "memory_budget_snapshot",
                        lambda: {"free_percent": 75, "swap_used_gb": 0})
    monkeypatch.setattr(video_rolling.runtime_coordinator, "ensure_active_memory_safe",
                        lambda _: None)

    def ffmpeg(command, _cancel, _owner, timeout=600):
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    monkeypatch.setattr(video_rolling, "_ffmpeg", ffmpeg)

    def synthetic(destination, frames, color):
        subprocess.run([
            shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=128x64:r=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-frames:v", str(frames), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-t", f"{frames / 24:.9f}", str(destination),
        ], check=True, capture_output=True, timeout=45)

    calls = []
    def generate(_model, params, output, **kwargs):
        assert params["duration"] == 6 and params["frames"] == 145
        assert params["_active_memory_guard"] is True
        assert params["prompt"].startswith(video_rolling.INITIAL_FACE_GUIDANCE) == with_photo
        assert params["prompt"].endswith("A still portrait gently moving")
        synthetic(output, 145, "red")
        calls.append(("generate", 145))

    def extend(source, output, amount, params, cancel, update, owner):
        info = video_rolling._probe_video(source)
        assert info["frames"] == 25, "must not feed full accumulated movie"
        assert amount == 6
        assert params["prompt"].startswith(video_rolling.EXTEND_FACE_GUIDANCE) == with_photo
        assert params["prompt"].endswith("A still portrait gently moving")
        synthetic(output, 73, "blue")
        calls.append(("extend", info["frames"], amount))

    monkeypatch.setattr(video_rolling.video_long, "extend", extend)
    photo = tmp_path / "test-portrait.png"
    if with_photo:
        photo.write_bytes(b"synthetic reference source, no image decoder used")
    params = {
        "duration": 10, "resolution": "540p", "fps": 24,
        "width": 128, "height": 64, "seed": 7,
        "prompt": "A still portrait gently moving", "profile": "standard",
        "quality": "fast", "first_frame": str(photo) if with_photo else None,
        "identity_lock": True, "continuation_mode": "rolling",
    }
    model = {"id": "ltx-test", "provider": "ltx-mlx"}
    checkpoints = tmp_path / "checkpoints"
    status = {}
    def update(**fields):
        status.update(fields)
    output = tmp_path / "result.mp4"
    with monkeypatch.context() as p:
        result = video_rolling.run(
            model, params, output, job_id="a" * 24, checkpoints=checkpoints,
            resume_job=None, generate=generate,
            cancel_event=threading.Event(), response_callback=lambda _: None,
            progress_callback=lambda _: None, phase_callback=lambda _: None,
            update=update,
        )
    assert calls == [("generate", 145), ("extend", 25, 6), ("extend", 25, 6)]
    assert result["frames"] == 241
    assert result["strategy"] == video_rolling.STRATEGY
    assert result["rolling_window_frames"] == 25
    assert result["rolling_identity_prompt_guidance"] is with_photo
    assert status["rolling_identity_prompt_guidance"] is with_photo
    assert result["audio"] is True
    assert len(result["rolling_stage_memory"]) == 3
    assert [m["stage"] for m in result["rolling_stage_memory"]] == [1, 2, 3]
    assert all(m["after_free_percent"] == 75 and m["after_swap_gb"] == 0
               for m in result["rolling_stage_memory"])
    assert status["rolling_stage_memory"] == result["rolling_stage_memory"]
    assert status["checkpoint_count"] == 3
    assert status["confirmed_duration"] == 10
    manifest = json.loads((checkpoints / ("a" * 24) / "checkpoint.json").read_text())
    assert [entry["seconds"] for entry in manifest["stages"]] == [6, 2, 2]
    assert all(not (checkpoints / ("a" * 24) / f"raw-{i}.partial.mp4").exists()
               for i in range(3))


def test_rolling_face_guidance_uses_source_only_when_enabled():
    original = "The person gently turns their head, smiles and blinks."
    for first_frame, lock in ((None, True), ("/managed/portrait.png", False)):
        params = {"prompt": original, "first_frame": first_frame,
                  "identity_lock": lock}
        assert video_rolling._face_prompt(params, extension=False) == original
        assert video_rolling._face_prompt(params, extension=True) == original
    params = {"prompt": original, "first_frame": "/managed/portrait.png",
              "identity_lock": True}
    initial = video_rolling._face_prompt(params, extension=False)
    extended = video_rolling._face_prompt(params, extension=True)
    assert initial.startswith(video_rolling.INITIAL_FACE_GUIDANCE)
    assert extended.startswith(video_rolling.EXTEND_FACE_GUIDANCE)
    assert initial.endswith(original) and extended.endswith(original)
    assert "eye shape" in initial and "iris placement" in extended
    assert "natural" in initial and "natural" in extended
    assert params["prompt"] == original, "must not mutate the user prompt"


def test_rolling_trim_preserves_facelike_detail_with_low_crf(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic source")
    info = {"frames": 145, "fps": 24, "width": 128, "height": 64,
            "duration": 145 / 24, "audio": True}
    commands = []
    monkeypatch.setattr(video_rolling, "_probe_video", lambda _: info)
    monkeypatch.setattr(video_rolling, "_validate_part",
                        lambda path, count, params: info)
    monkeypatch.setattr(video_rolling, "_ffmpeg",
                        lambda command, *a, **kw: commands.append(command))
    monkeypatch.setattr(video_rolling.gate, "blocked", lambda: False)
    video_rolling._clip_frames(source, tmp_path / "context.mp4",
                               start=120, count=25,
                               cancel=threading.Event(), owner="test")
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("-crf") + 1] == str(video_rolling.CLIP_CRF) == "10"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    # Only a frame-selection and timestamp transform: do not smooth away
    # blinks, irises or facial expressions in the transport layer.
    assert command[command.index("-vf") + 1].startswith("select=")
    assert "scale=" not in command[command.index("-vf") + 1]
