from pathlib import Path

import pytest
from pydantic import ValidationError

from agent import shorts_composer, shorts_jobs
from agent.shorts_planner import ShortProject


def project_payload(**changes):
    payload = {
        "schema_version": 2,
        "title": "Cast voice test",
        "duration": 10,
        "aspect_ratio": "9:16",
        "language": "de",
        "voice_enabled": True,
        "voice": "Serena",
        "music_enabled": False,
        "subtitles_enabled": True,
        "cast": [
            {"id": "nobby", "name": "Nobby", "voice": "Nobby Voice"},
            {"id": "anna", "name": "Anna", "voice": "Anna_Clone"},
        ],
        "scenes": [
            {
                "id": "scene-1",
                "duration": 5,
                "narration": "Hallo von Nobby.",
                "caption": "Hallo",
                "speaker": "nobby",
                "video_prompt": "Nobby presents a product",
            },
            {
                "id": "scene-2",
                "duration": 5,
                "narration": "Hallo von Anna.",
                "caption": "Hallo Anna",
                "speaker": "anna",
                "video_prompt": "Anna responds",
            },
        ],
    }
    payload.update(changes)
    return payload


def test_cast_member_voice_overrides_project_voice():
    project = ShortProject.model_validate(project_payload())

    assert project.voice_for_scene(project.scenes[0]) == "Nobby Voice"
    assert project.voice_for_scene(project.scenes[1]) == "Anna_Clone"


def test_scene_without_cast_voice_falls_back_to_project_voice():
    payload = project_payload()
    payload["cast"][0]["voice"] = None
    project = ShortProject.model_validate(payload)

    assert project.voice_for_scene(project.scenes[0]) == "Serena"


def test_unknown_scene_speaker_is_rejected():
    payload = project_payload()
    payload["scenes"][0]["speaker"] = "missing-person"

    with pytest.raises(ValidationError, match="not present in cast"):
        ShortProject.model_validate(payload)


def test_duplicate_cast_ids_are_rejected():
    payload = project_payload()
    payload["cast"][1]["id"] = "nobby"

    with pytest.raises(ValidationError, match="cast ids must be unique"):
        ShortProject.model_validate(payload)


def test_managed_voice_labels_may_contain_spaces():
    project = ShortProject.model_validate(project_payload())

    assert project.cast[0].voice == "Nobby Voice"


def test_scene_tts_sends_cast_voice_per_scene(tmp_path, monkeypatch):
    project = ShortProject.model_validate(project_payload())
    payloads = []

    monkeypatch.setattr(shorts_jobs, "SHORTS_DIRECTORY", tmp_path)
    monkeypatch.setattr(shorts_jobs, "get_short_job", lambda _job_id: {"cancel_requested": False})
    monkeypatch.setattr(shorts_composer.subprocess, "check_output", lambda *args, **kwargs: "1.0\n")

    def fake_ffmpeg(command, *, cwd, cancel_check, timeout):
        assert cancel_check() is False
        Path(cwd, "voiceover-mix.mp3").write_bytes(b"mixed-audio")

    monkeypatch.setattr(shorts_jobs, "_run_ffmpeg", fake_ffmpeg)

    def request(payload):
        payloads.append(payload)
        return b"scene-audio"

    audio = shorts_composer.scene_tts("abcdef0123456789abcdef01", project, request)

    assert audio == b"mixed-audio"
    assert [payload["voice"] for payload in payloads] == ["Nobby Voice", "Anna_Clone"]
    assert [payload["input"] for payload in payloads] == ["Hallo von Nobby.", "Hallo von Anna."]


def test_shorts_editor_exposes_cast_voice_assignment_ui():
    source = Path("frontend/assets/chat/shorts-project-editor.js").read_text(encoding="utf-8")

    assert "/api/mlx/audio/voices/manage" in source
    assert "Cast & voices" in source
    assert "project.cast" in source
    assert "scene, 'speaker'" in source
