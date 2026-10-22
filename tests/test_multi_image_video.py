"""CPU contracts plus real ffmpeg composition; no model loads."""
import shutil
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import video_multi_image as multi
import video_providers as provider
import video_providers_mlx as mlx
import video_registry
import video_service as service
from agent import app as agent, media_queue


@pytest.fixture
def managed(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(agent, "VIDEO_UPLOAD_DIRECTORY", tmp_path)
    monkeypatch.setattr(service, "_multi_capabilities", lambda: {"native_keyframes": True})
    monkeypatch.setattr(service, "i2v_source_size", lambda _: (384, 256))
    paths = [tmp_path / f"{index:012x}.png" for index in range(5)]
    from PIL import Image
    for index, path in enumerate(paths):
        Image.new("RGB", (384, 256), (index * 40, 100, 120)).save(path)
    return paths


def request(paths, mode="keyframes", **options):
    return service.JobCreate(operation="multi_i2v", chat_id="chat", chat_revision=0,
        payload={"prompt": "A smooth moving camera", "quality": "fast", "aspect_ratio": "16:9",
                 "multi_image_mode": mode, "images": [{"path": str(path)} for path in paths], **options})


@pytest.mark.parametrize("count", [2, 3, 5])
def test_temporal_anchors_include_start_and_end(managed, count):
    payload = request(managed[:count]).payload
    indices = [image.frame_index for image in payload.images]
    assert indices == multi.frame_positions(count, 121)
    assert indices[0] == 0 and indices[-1] == 120
    assert payload.resize_mode == "contain"


@pytest.mark.parametrize("options", [
    {"first_frame": "/tmp/not-managed.png"}, {"quality": "preview"},
    {"model": video_registry.LTX_ID}, {"resume_from": "a" * 24},
])
def test_invalid_multi_combinations_fail_before_loading(managed, options):
    with pytest.raises(ValidationError):
        request(managed[:2], **options)


def test_limits_paths_positions_and_unavailable_engine(managed, monkeypatch):
    for paths in [managed[:1], managed + managed[:1], [managed[0], Path("/etc/passwd")]]:
        with pytest.raises(ValidationError):
            request(paths)
    for indices in [[0, 121], [60, 0], [0, 0]]:
        with pytest.raises(ValidationError):
            request(managed[:2], images=[{"path": str(path), "frame_index": index}
                                        for path, index in zip(managed, indices)])
    monkeypatch.setattr(service, "_multi_capabilities", lambda: {"native_keyframes": False})
    with pytest.raises(ValidationError, match="keine nativen Keyframes"):
        request(managed[:2])
    assert request(managed[:2], "scenes").payload.multi_image_mode == "scenes"


def test_explicit_positions_strength_and_single_image_unchanged(managed):
    anchors = [{"path": str(path), "frame_index": index, "strength": 0.8}
               for path, index in zip(managed, [0, 32, 120])]
    assert [i.frame_index for i in request(managed[:3], images=anchors).payload.images] == [0, 32, 120]
    single = service.JobCreate(operation="i2v", chat_id="chat", chat_revision=0,
                              payload={"prompt": "Move slowly", "first_frame": str(managed[0])})
    assert single.payload.images == [] and single.payload.first_frame == str(managed[0])
    with pytest.raises(ValidationError):
        service.JobCreate(operation="t2v", chat_id="chat", chat_revision=0,
                          payload=request(managed[:2]).payload.model_dump())


def test_capability_probe_reads_api_and_fails_closed(tmp_path):
    package = tmp_path / "packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx"
    (package / "utils").mkdir(parents=True)
    assert multi.keyframe_capabilities(tmp_path)["native_keyframes"] is False
    (package / "distilled.py").write_text("def generate_two_stage(self, *, images=None): pass")
    (package / "ti2vid_two_stages.py").write_text("def generate_and_save(self, *, images=None): pass")
    (package / "utils/args.py").write_text("class ImageConditioningInput: pass")
    assert multi.keyframe_capabilities(tmp_path)["native_keyframes"] is True
    (package / "distilled.py").write_text("def generate_two_stage(self, **kwargs): pass")
    assert multi.keyframe_capabilities(tmp_path)["native_keyframes"] is False


def test_agent_resolves_upload_and_library_sources(managed, monkeypatch):
    monkeypatch.setattr(agent, "compile_video_prompt", lambda value: value)
    monkeypatch.setattr(agent, "_resolve_image_artifact_source", lambda _: managed[1])
    action = agent.ChatActionRequest(prompt="Slow camera motion", multi_image_mode="keyframes",
        multi_images=[{"stored_path": str(managed[0])}, {"artifact_id": "image-id"}])
    payload = agent._video_payload(action, "multi_i2v")
    assert [image["path"] for image in payload["images"]] == [str(p) for p in managed[:2]]
    assert "first_frame" not in payload
    action.multi_images[0] = {"stored_path": "/etc/passwd"}
    with pytest.raises(HTTPException):
        agent._video_payload(action, "multi_i2v")


def test_plain_prompt_from_explicit_multi_image_ui_routes_to_video(managed):
    action = agent.ChatActionRequest(prompt="A red ball rolls slowly", action="video_generate",
        resolved_target="video", multi_image_mode="keyframes",
        multi_images=[{"stored_path": str(path)} for path in managed[:2]])
    with mock.patch.object(agent, "_start_chat_video_job", return_value={
        "id": "a" * 24, "status": "queued", "operation": "multi_i2v",
    }) as start:
        result = agent.run_chat_action(action)
    assert result["tool"] == "video_generate"
    start.assert_called_once()


def test_provider_prepares_every_anchor_and_passes_positions(managed, tmp_path):
    payload = request(managed[:3]).payload.model_dump()
    output = tmp_path / "out.mp4"
    def worker(model, params, target, **kwargs):
        assert [a["frame_index"] for a in params["images"]] == [0, 60, 120]
        assert all(Path(a["path"]).is_file() for a in params["images"])
        target.write_bytes(b"video")
        return False, {}
    with mock.patch.object(mlx, "availability", return_value=(True, "ready")), \
         mock.patch.object(multi, "keyframe_capabilities", return_value={"native_keyframes": True}), \
         mock.patch.object(mlx, "_run_warm_worker", side_effect=worker), \
         mock.patch.object(mlx, "_probe_video", return_value={"audio": True}):
        assert mlx.generate(video_registry.builtin_mlx_model(), payload, output,
                            cancel_event=threading.Event())["audio"]
    command = mlx._command(video_registry.builtin_mlx_model(), payload, output)
    assert command.count("--image") == 3


@pytest.fixture
def clips(tmp_path, monkeypatch):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe unavailable")
    monkeypatch.setattr(multi, "FFMPEG", ffmpeg)
    monkeypatch.setattr(provider, "FFPROBE", ffprobe)
    paths = [tmp_path / f"clip-{i}.mp4" for i in range(2)]
    for index, path in enumerate(paths):
        command = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                   f"color=c={'red' if index == 0 else 'blue'}:s=64x64:r=8:d=0.5"]
        if index == 0:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5", "-c:a", "aac"]
        subprocess.run(command + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
    return paths


def test_real_composition_preserves_audio_and_fills_silent_scene(clips, tmp_path):
    params = dict(width=64, height=64, fps=8, duration=0.5)
    output = tmp_path / "joined.mp4"
    info = multi.compose_scenes(clips, output, params, threading.Event())
    assert info["audio"] and info["width"] == 64 and info["fps"] == 8
    assert 0.95 <= info["duration"] <= 1.1
    assert info["frames"] == 8


def test_failed_scene_retry_reuses_completed_segment(clips, tmp_path):
    checkpoints = tmp_path / "checkpoints"
    params = dict(width=64, height=64, fps=8, duration=0.5, seed=1,
                  images=[{"path": "one.png"}, {"path": "two.png"}])
    state = {}
    def failing(model, payload, output, **kwargs):
        if payload["first_frame"] == "two.png":
            output.write_bytes(b"partial")
            raise RuntimeError("out of memory")
        shutil.copy2(clips[0], output)
    callbacks = dict(response_callback=lambda _: None, progress_callback=lambda _: None,
                     phase_callback=lambda _: None, update=lambda **values: state.update(values))
    old = "a" * 24
    with pytest.raises(RuntimeError, match="out of memory"):
        multi.generate_scenes({}, params, tmp_path / "failed.mp4", job_id=old,
            checkpoints=checkpoints, resume_job=None, generate=failing,
            cancel_event=threading.Event(), **callbacks)
    assert len(state["segments"]) == 1
    assert not (checkpoints / old / "scene-1.mp4").exists()
    generated = []
    def success(model, payload, output, **kwargs):
        generated.append(payload["first_frame"])
        shutil.copy2(clips[1], output)
    info = multi.generate_scenes({}, params, tmp_path / "success.mp4", job_id="b" * 24,
        checkpoints=checkpoints, resume_job={"id": old, "segments": state["segments"]},
        generate=success, cancel_event=threading.Event(), **callbacks)
    assert generated == ["two.png"] and info["segments"][0]["reused"]
    assert not (checkpoints / ("b" * 24)).exists()


def test_composition_cancel_terminates_process():
    cancel = threading.Event(); cancel.set()
    process = mock.Mock()
    process.poll.return_value = None
    with mock.patch.object(subprocess, "Popen", return_value=process):
        with pytest.raises(provider.ProviderCancelled):
            multi.run_ffmpeg(["ffmpeg"], cancel)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)


def test_retry_validation_requires_identical_payload_and_chat(managed, monkeypatch):
    before = request(managed[:2], "scenes")
    native_id = "a" * 24
    previous = {"id": native_id, "status": "failed", "chat_id": "chat",
                "payload": before.payload.model_dump()}
    monkeypatch.setattr(service, "_jobs", {native_id: previous})
    monkeypatch.setattr(service, "preflight_profile", lambda *_: None)
    resumed = request(managed[:2], "scenes", resume_from=native_id)
    assert service.preflight(resumed)["available"]
    resumed.payload.seed = 99
    with pytest.raises(HTTPException):
        service.preflight(resumed)
    resumed.payload.seed = 0
    previous["source_versions"] = service._multi_source_versions(before.payload)
    managed[0].write_bytes(b"changed")
    with pytest.raises(HTTPException, match="Quellbilder"):
        service.preflight(resumed)


def test_queue_retry_and_native_scene_progress_are_preserved(monkeypatch):
    job_id, native_id = "a" * 24, "b" * 24
    previous = {"kind": "video", "status": "failed", "native_job_id": native_id,
                "request": {"operation": "multi_i2v", "payload": {"multi_image_mode": "scenes"}}}
    monkeypatch.setattr(media_queue, "_loaded", True)
    monkeypatch.setattr(media_queue, "_jobs", {job_id: previous})
    with mock.patch.object(media_queue, "enqueue", return_value={"id": "c" * 24}) as enqueue:
        media_queue.retry_video_scenes(job_id)
    assert enqueue.call_args.args[1]["payload"]["resume_from"] == native_id
    assert "resume_from" not in previous["request"]["payload"]
    with mock.patch.object(media_queue, "_update") as update:
        media_queue._mirror_native(job_id, {"scene_number": 2, "scene_count": 3, "multi_image_mode": "scenes"})
    assert update.call_args.kwargs["scene_number"] == 2
