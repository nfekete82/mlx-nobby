import json
import os
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.responses import Response
import pytest

from agent import shorts_jobs
from agent.shorts_planner import ShortProject


def project(**changes):
    value = {
        "title": "Berlin in zehn Jahren",
        "duration": 20,
        "music_enabled": False,
        "scenes": [
            {
                "id": f"scene-{index}",
                "duration": 5,
                "narration": f"Szene {index}",
                "video_prompt": f"Future Berlin scene {index}",
            }
            for index in range(1, 5)
        ],
    }
    value.update(changes)
    return ShortProject.model_validate(value)


def configure_store(tmp_path, monkeypatch):
    directory = tmp_path / "shorts"
    monkeypatch.setattr(shorts_jobs, "SHORTS_DIRECTORY", directory)
    monkeypatch.setattr(shorts_jobs, "SHORTS_JOBS_FILE", directory / "jobs.json")
    monkeypatch.setattr(shorts_jobs, "MUSIC_DIRECTORY", tmp_path / "music")
    def render(command, *, cwd, cancel_check, timeout):
        assert not cancel_check()
        Path(command[-1]).write_bytes(b"final-mp4")
    monkeypatch.setattr(shorts_jobs, "_run_ffmpeg", render)
    with shorts_jobs._workers_lock:
        shorts_jobs._workers.clear()


class CompletedVideoAPI:
    def __init__(self):
        self.calls = []
        self.created = 0

    def __call__(self, method, path, payload=None, timeout=15):
        self.calls.append((method, path, payload, timeout))
        if method == "POST" and path == "/jobs":
            self.created += 1
            return {"id": f"{self.created:024x}", "status": "queued"}
        if method == "GET":
            child_id = path.rsplit("/", 1)[-1]
            return {
                "id": child_id,
                "status": "completed",
                "result": {"path": f"/videos/{child_id}.mp4"},
            }
        raise AssertionError((method, path))


def tts_audio(_payload):
    return b"ID3-short-voiceover"


def mark_video_completed(job_id):
    value = project()
    shorts_jobs._update_job(
        job_id,
        status="video_completed",
        phase="video_completed",
        current_scene=len(value.scenes),
        scene_results=[{
            "scene_id": scene.id,
            "duration": scene.duration,
            "status": "completed",
            "video_job_id": f"{index:024x}",
            "path": f"/videos/{index:024x}.mp4",
        } for index, scene in enumerate(value.scenes, 1)],
        active_video_job_id=None,
    )


def mark_tts_completed(job_id):
    mark_video_completed(job_id)
    output = shorts_jobs._tts_output_path(job_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"ID3-voiceover")
    shorts_jobs._update_job(
        job_id,
        status="tts_completed",
        phase="tts_completed",
        tts_status="completed",
        tts_path=str(output),
        tts_started_at=1.0,
        tts_finished_at=2.0,
    )


def test_job_is_created_persistently(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(
        project(), chat_id="chat-one", run_id="run-one", chat_revision=3,
    )

    assert shorts_jobs.SHORTS_JOBS_FILE.is_file()
    stored = shorts_jobs.get_short_job(job["id"])
    assert stored["kind"] == "shorts"
    assert stored["project"]["aspect_ratio"] == "9:16"
    assert stored["current_scene"] == 0
    assert stored["scene_results"] == []
    assert stored["cancel_requested"] is False
    assert stored["tts_status"] == "pending"
    assert stored["tts_path"] is None
    assert stored["tts_metadata"] is None
    assert stored["music_status"] == "disabled"
    assert stored["music_style"] == "cinematic"
    assert stored["music_path"] is None
    assert stored["subtitles_path"] is None
    assert stored["compose_status"] == "pending"
    assert stored["final_path"] is None


def test_four_scenes_run_sequentially_and_finish(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=api, tts_request_fn=tts_audio,
        poll_interval=0,
    )

    assert result["status"] == "completed"
    assert result["phase"] == "completed"
    assert result["current_scene"] == 4
    assert len(result["scene_results"]) == 4
    assert [call[:2] for call in api.calls] == [
        item
        for index in range(1, 5)
        for item in (("POST", "/jobs"), ("GET", f"/jobs/{index:024x}"))
    ]
    for index, call in enumerate(api.calls[::2]):
        payload = call[2]["payload"]
        assert payload["prompt"] == f"Future Berlin scene {index + 1}"
        assert payload["duration"] == 5
        assert payload["aspect_ratio"] == "9:16"


def test_child_id_is_persisted_before_polling(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "a" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST":
            return {"id": child_id, "status": "queued"}
        stored = shorts_jobs.get_short_job(job["id"])
        assert stored["active_video_job_id"] == child_id
        return {"id": child_id, "status": "failed", "error": "stop"}

    shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert shorts_jobs.get_short_job(job["id"])["active_video_job_id"] == child_id


def test_resume_skips_completed_scene(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    first_child = "f" * 24
    shorts_jobs._update_job(
        job["id"],
        status="running",
        current_scene=0,
        scene_results=[{
            "scene_id": "scene-1", "duration": 5, "status": "completed",
            "video_job_id": first_child, "path": f"/videos/{first_child}.mp4",
        }],
    )

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=api, tts_request_fn=tts_audio,
        poll_interval=0,
    )

    assert result["status"] == "completed"
    assert api.created == 3
    assert [entry["scene_id"] for entry in result["scene_results"]] == [
        "scene-1", "scene-2", "scene-3", "scene-4",
    ]


def test_resume_polls_existing_child_before_starting_another(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    existing_child = "e" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=existing_child,
    )

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=api, tts_request_fn=tts_audio,
        poll_interval=0,
    )

    assert result["status"] == "completed"
    assert api.calls[0][:2] == ("GET", f"/jobs/{existing_child}")
    assert api.created == 3
    assert result["scene_results"][0]["video_job_id"] == existing_child


def test_resume_retries_existing_child_while_video_service_starts(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    api = CompletedVideoAPI()
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    existing_child = "9" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=existing_child,
    )
    attempts = 0

    def request(method, path, payload=None, timeout=15):
        nonlocal attempts
        if method == "GET" and attempts == 0:
            attempts += 1
            raise HTTPException(503, "Video-Service nicht erreichbar")
        return api(method, path, payload, timeout)

    with mock.patch.object(shorts_jobs.time, "sleep") as sleep:
        result = shorts_jobs.run_short_job(
            job["id"], request_fn=request, tts_request_fn=tts_audio,
            poll_interval=1,
        )

    assert result["status"] == "completed"
    assert sleep.call_count == 1
    assert api.calls[0][:2] == ("GET", f"/jobs/{existing_child}")


def test_child_failure_fails_short(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "b" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST":
            return {"id": child_id, "status": "queued"}
        return {"id": child_id, "status": "failed", "error": "LTX failed"}

    result = shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert result["status"] == "failed"
    assert result["error"] == "LTX failed"
    assert result["finished_at"] is not None


def test_cancel_requests_active_video_cancellation(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "c" * 24
    shorts_jobs._update_job(
        job["id"], status="running", active_video_job_id=child_id,
    )
    calls = []

    def request(method, path, payload=None, timeout=15):
        calls.append((method, path, payload, timeout))
        return {"id": child_id, "status": "cancelled"}

    result = shorts_jobs.cancel_short_job(job["id"], request_fn=request)

    assert calls == [("POST", f"/jobs/{child_id}/cancel", {}, 30)]
    assert result["status"] == "cancelled"
    assert result["cancel_requested"] is True
    assert result["finished_at"] is not None


def test_cancel_request_wins_over_concurrent_child_failure(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    child_id = "d" * 24

    def request(method, path, payload=None, timeout=15):
        if method == "POST" and path == "/jobs":
            return {"id": child_id, "status": "queued"}
        if method == "GET":
            shorts_jobs._update_job(job["id"], cancel_requested=True)
            return {"id": child_id, "status": "failed", "error": "cancel race"}
        return {"id": child_id, "status": "cancelled"}

    result = shorts_jobs.run_short_job(job["id"], request_fn=request, poll_interval=0)

    assert result["status"] == "cancelled"
    assert result["error"] is None


def test_resume_short_jobs_registers_all_resumable_jobs(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    queued = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    video_completed = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    tts_completed = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    shorts_jobs._update_job(
        video_completed["id"], status="video_completed", phase="video_completed",
    )
    shorts_jobs._update_job(
        tts_completed["id"], status="tts_completed", phase="tts_completed",
    )

    with mock.patch.object(shorts_jobs, "start_short_job") as start:
        resumed = shorts_jobs.resume_short_jobs()

    assert resumed == [queued["id"], video_completed["id"], tts_completed["id"]]
    assert start.call_args_list == [
        mock.call(
            queued["id"], request_fn=None, tts_request_fn=None, compose_fn=None,
            poll_interval=1.0,
        ),
        mock.call(
            video_completed["id"], request_fn=None, tts_request_fn=None,
            compose_fn=None,
            poll_interval=1.0,
        ),
        mock.call(
            tts_completed["id"], request_fn=None, tts_request_fn=None,
            compose_fn=None,
            poll_interval=1.0,
        ),
    ]


def test_narration_is_composed_in_scene_order():
    assert shorts_jobs.narration_for_project(project()) == (
        "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4"
    )


def test_tts_adapter_uses_existing_speech_endpoint():
    upstream = Response(content=b"ID3-audio", media_type="audio/mpeg")
    with mock.patch.dict(
        os.environ, {"SPEECH_SERVICE_URL": "http://127.0.0.1:9050"},
    ), mock.patch.object(
        shorts_jobs.service_proxy, "forward", return_value=upstream,
    ) as forward:
        audio = shorts_jobs._request_tts({"input": "Hallo", "language": "de"})

    assert audio == b"ID3-audio"
    assert forward.call_args.args[0] == "http://127.0.0.1:9050/v1/audio/speech"
    assert json.loads(forward.call_args.args[1]) == {
        "input": "Hallo", "language": "de",
    }
    assert forward.call_args.kwargs == {"timeout": 900}


def test_tts_runs_once_after_video_and_persists_output(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])
    calls = []

    def tts(payload):
        calls.append(payload)
        return b"ID3-voiceover"

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), tts_request_fn=tts,
    )

    assert calls == [{
        "input": "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4",
        "language": "de",
    }]
    assert result["status"] == result["phase"] == "completed"
    assert result["tts_status"] == "completed"
    assert Path(result["tts_path"]).read_bytes() == b"ID3-voiceover"
    assert result["tts_started_at"] is not None
    assert result["tts_finished_at"] is not None
    assert result["tts_metadata"] == {
        "mime_type": "audio/mpeg",
        "language": "de",
        "scene_count": 4,
        "narration_characters": 34,
    }


def test_tts_resume_reuses_existing_successful_output(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])
    output = shorts_jobs.SHORTS_DIRECTORY / job["id"] / "voiceover.mp3"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing")
    shorts_jobs._update_job(
        job["id"], tts_status="completed", tts_path=str(output),
        tts_started_at=1.0, tts_finished_at=2.0,
    )
    tts = mock.Mock(side_effect=AssertionError("must not regenerate TTS"))

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), tts_request_fn=tts,
    )

    tts.assert_not_called()
    assert result["status"] == "completed"
    assert result["tts_path"] == str(output)


def test_tts_resume_reuses_atomic_output_even_before_status_checkpoint(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])
    output = shorts_jobs._tts_output_path(job["id"])
    output.parent.mkdir(parents=True)
    output.write_bytes(b"existing-after-crash")
    tts = mock.Mock(side_effect=AssertionError("must not regenerate TTS"))

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), tts_request_fn=tts,
    )

    tts.assert_not_called()
    assert result["status"] == "completed"
    assert result["tts_status"] == "completed"
    assert result["tts_path"] == str(output)


def test_tts_failure_fails_short(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])

    result = shorts_jobs.run_short_job(
        job["id"],
        request_fn=mock.Mock(),
        tts_request_fn=mock.Mock(side_effect=RuntimeError("TTS failed")),
    )

    assert result["status"] == "failed"
    assert result["tts_status"] == "failed"
    assert result["error"] == "TTS failed"


def test_cancel_before_tts_skips_request(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])
    shorts_jobs._update_job(job["id"], cancel_requested=True)
    tts = mock.Mock(side_effect=AssertionError("must not start TTS"))

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), tts_request_fn=tts,
    )

    tts.assert_not_called()
    assert result["status"] == "cancelled"


def test_cancel_during_tts_discards_output(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_video_completed(job["id"])

    def tts(_payload):
        shorts_jobs._update_job(job["id"], cancel_requested=True)
        return b"ID3-discard-me"

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), tts_request_fn=tts,
    )

    assert result["status"] == "cancelled"
    assert result["tts_path"] is None
    assert result["tts_status"] == "cancelled"
    assert not (shorts_jobs.SHORTS_DIRECTORY / job["id"] / "voiceover.mp3").exists()


def test_ass_uses_scene_order_and_exact_time_windows():
    ass = shorts_jobs.subtitles_for_project(project())

    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert dialogues == [
        "Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Szene 1",
        "Dialogue: 0,0:00:05.00,0:00:10.00,Default,,0,0,0,,Szene 2",
        "Dialogue: 0,0:00:10.00,0:00:15.00,Default,,0,0,0,,Szene 3",
        "Dialogue: 0,0:00:15.00,0:00:20.00,Default,,0,0,0,,Szene 4",
    ]


def test_compose_uses_ordered_clips_voiceover_and_persists_output(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_tts_completed(job["id"])
    calls = []

    def compose(command, *, cwd, cancel_check, timeout):
        calls.append((command, cwd, timeout))
        assert not cancel_check()
        Path(command[-1]).write_bytes(b"composed-mp4")

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), compose_fn=compose,
    )

    assert result["status"] == result["phase"] == "completed"
    assert result["compose_status"] == "completed"
    assert Path(result["final_path"]).read_bytes() == b"composed-mp4"
    assert Path(result["subtitles_path"]).is_file()
    assert result["compose_started_at"] is not None
    assert result["compose_finished_at"] is not None
    command = calls[0][0]
    inputs = [command[index + 1] for index, value in enumerate(command) if value == "-i"]
    assert inputs == [
        "/videos/000000000000000000000001.mp4",
        "/videos/000000000000000000000002.mp4",
        "/videos/000000000000000000000003.mp4",
        "/videos/000000000000000000000004.mp4",
        result["tts_path"],
    ]
    assert "-stream_loop" not in command
    assert result["music_status"] == "disabled"
    filters = command[command.index("-filter_complex") + 1]
    assert "concat=n=4:v=1:a=0" in filters
    assert "ass=subtitles.ass" in filters
    assert "[0:a" not in filters
    maps = [command[index + 1] for index, value in enumerate(command) if value == "-map"]
    assert maps == ["[subtitled]", "4:a:0"]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[command.index("-t", command.index("-filter_complex")) + 1] == "20"


def test_ffmpeg_failure_fails_short(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_tts_completed(job["id"])

    result = shorts_jobs.run_short_job(
        job["id"],
        request_fn=mock.Mock(),
        compose_fn=mock.Mock(side_effect=RuntimeError("FFmpeg failed: broken")),
    )

    assert result["status"] == result["phase"] == "failed"
    assert result["compose_status"] == "failed"
    assert result["error"] == "FFmpeg failed: broken"


def test_completed_final_is_not_rendered_again(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    final_path = shorts_jobs._final_output_path(job["id"])
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"existing-final")
    shorts_jobs._update_job(
        job["id"],
        status="completed",
        phase="completed",
        compose_status="completed",
        final_path=str(final_path),
        compose_finished_at=2.0,
        finished_at=2.0,
    )
    compose = mock.Mock(side_effect=AssertionError("must not render"))

    result = shorts_jobs.run_short_job(job["id"], compose_fn=compose)

    compose.assert_not_called()
    assert result["final_path"] == str(final_path)


def test_cancel_before_compose_skips_ffmpeg(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_tts_completed(job["id"])
    shorts_jobs._update_job(job["id"], cancel_requested=True)
    compose = mock.Mock(side_effect=AssertionError("must not render"))

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), compose_fn=compose,
    )

    compose.assert_not_called()
    assert result["status"] == "cancelled"
    assert result["final_path"] is None


def test_cancel_during_compose_discards_final_output(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_tts_completed(job["id"])

    def compose(command, *, cwd, cancel_check, timeout):
        shorts_jobs._update_job(job["id"], cancel_requested=True)
        Path(command[-1]).write_bytes(b"discard-me")

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), compose_fn=compose,
    )

    assert result["status"] == "cancelled"
    assert result["compose_status"] == "cancelled"
    assert result["final_path"] is None
    assert not shorts_jobs._final_output_path(job["id"]).exists()
    assert not shorts_jobs._final_output_path(job["id"]).with_suffix(".mp4.tmp").exists()


def test_missing_music_library_uses_cinematic_and_still_completes(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(
        project(music_enabled=True), chat_id="chat-one",
    )
    mark_tts_completed(job["id"])

    result = shorts_jobs.run_short_job(job["id"], request_fn=mock.Mock())

    assert result["status"] == "completed"
    assert result["music_status"] == "missing"
    assert result["music_style"] == "cinematic"
    assert result["music_path"] is None


def test_music_selection_finds_style_track_deterministically(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    style_directory = shorts_jobs.MUSIC_DIRECTORY / "ambient"
    style_directory.mkdir(parents=True)
    (style_directory / "b.mp3").write_bytes(b"b")
    (style_directory / "a.wav").write_bytes(b"a")
    job = shorts_jobs.create_short_job(
        project(music_enabled=True, music_style="ambient"), chat_id="chat-one",
    )
    stored = shorts_jobs.get_short_job(job["id"])

    first = shorts_jobs._select_music_track(job["id"], stored)
    second = shorts_jobs._select_music_track(job["id"], stored)

    assert first == second
    assert first[0] == "selected"
    assert first[1] == "ambient"
    assert first[2].parent == style_directory


def test_music_resume_reuses_persisted_track(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    style_directory = shorts_jobs.MUSIC_DIRECTORY / "dark"
    style_directory.mkdir(parents=True)
    selected = style_directory / "selected.mp3"
    selected.write_bytes(b"selected")
    job = shorts_jobs.create_short_job(
        project(music_enabled=True, music_style="dark"), chat_id="chat-one",
    )
    shorts_jobs._update_job(
        job["id"], music_status="selected", music_path=str(selected),
    )
    (style_directory / "new-track.mp3").write_bytes(b"new")

    status, style, path = shorts_jobs._select_music_track(
        job["id"], shorts_jobs.get_short_job(job["id"]),
    )

    assert (status, style, path) == ("selected", "dark", selected.resolve())


def test_music_path_outside_library_is_rejected(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside")

    with pytest.raises(ValueError, match="inside the music library"):
        shorts_jobs._validated_music_path(outside, "cinematic")


def test_compose_adds_music_loop_ducking_trim_and_fade(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    style_directory = shorts_jobs.MUSIC_DIRECTORY / "futuristic"
    style_directory.mkdir(parents=True)
    track = style_directory / "pulse.mp3"
    track.write_bytes(b"music")
    job = shorts_jobs.create_short_job(
        project(music_enabled=True, music_style="futuristic"), chat_id="chat-one",
    )
    mark_tts_completed(job["id"])
    commands = []

    def compose(command, *, cwd, cancel_check, timeout):
        commands.append(command)
        Path(command[-1]).write_bytes(b"music-video")

    result = shorts_jobs.run_short_job(
        job["id"], request_fn=mock.Mock(), compose_fn=compose,
    )

    command = commands[0]
    inputs = [command[index + 1] for index, value in enumerate(command) if value == "-i"]
    assert inputs[-2:] == [result["tts_path"], str(track.resolve())]
    assert command[command.index("-stream_loop") + 1] == "-1"
    filters = command[command.index("-filter_complex") + 1]
    assert "sidechaincompress=" in filters
    assert "volume=0.18" in filters
    assert "atrim=duration=20[music]" in filters
    assert "afade=t=out:st=18:d=2" in filters
    assert "[voice_mix][ducked]amix=" in filters
    assert "[0:a" not in filters
    maps = [command[index + 1] for index, value in enumerate(command) if value == "-map"]
    assert maps == ["[subtitled]", "[audio]"]
    assert result["music_status"] == "selected"
    assert result["music_style"] == "futuristic"
    assert result["music_path"] == str(track.resolve())


def test_composer_respects_ffmpeg_path_environment(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    job = shorts_jobs.create_short_job(project(), chat_id="chat-one")
    mark_tts_completed(job["id"])
    monkeypatch.setenv("FFMPEG_PATH", "/custom/bin/ffmpeg")

    command = shorts_jobs._compose_command(
        shorts_jobs.get_short_job(job["id"]), tmp_path / "final.mp4",
    )

    assert command[0] == "/custom/bin/ffmpeg"
