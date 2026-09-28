import pytest
from pydantic import ValidationError

from agent import shorts_jobs, shorts_studio
from agent.shorts_planner import ShortProject, _planning_messages


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
    with shorts_jobs._workers_lock:
        shorts_jobs._workers.clear()


def completed_source(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    value = project()
    job = shorts_jobs.create_short_job(value, chat_id="chat-one", chat_revision=4)
    results = [
        {
            "scene_id": scene.id,
            "duration": scene.duration,
            "status": "completed",
            "video_job_id": f"{index:024x}",
            "path": f"/videos/{index:024x}.mp4",
        }
        for index, scene in enumerate(value.scenes, 1)
    ]
    shorts_jobs._update_job(
        job["id"],
        status="running",
        phase="video",
        current_scene=4,
        scene_results=results,
    )
    return shorts_jobs.get_short_job(job["id"])


def test_voice_defaults_preserve_existing_speech_service_behavior():
    value = project()

    assert value.voice is None
    assert value.voice_speed == 1.0
    assert shorts_jobs.tts_payload_for_project(value) == {
        "input": "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4",
        "language": "de",
    }


def test_explicit_voice_and_speed_are_forwarded_to_tts():
    value = project(voice="Pervin", voice_speed=1.1)

    assert shorts_jobs.tts_payload_for_project(value) == {
        "input": "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4",
        "language": "de",
        "voice": "Pervin",
        "speed": 1.1,
    }

    metadata = shorts_jobs._tts_metadata(
        value,
        shorts_jobs.narration_for_project(value),
    )
    assert metadata["voice"] == "Pervin"
    assert metadata["speed"] == 1.1


def test_voice_name_and_speed_are_bounded():
    with pytest.raises(ValidationError):
        project(voice="../../outside")

    with pytest.raises(ValidationError):
        project(voice_speed=0.49)

    with pytest.raises(ValidationError):
        project(voice_speed=2.01)


def test_planner_does_not_invent_voice_configuration():
    system = _planning_messages("Ein Short über Berlin")[0]["content"]

    assert "leave voice null" in system
    assert "Never invent a voice name" in system


def test_narration_only_revision_reuses_all_completed_video_scenes(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)

    revised = shorts_studio.create_scene_revision(
        source["id"],
        "scene-2",
        narration="Eine neue Erzählerzeile",
        voice="Pervin",
        voice_speed=1.1,
    )

    assert revised["id"] != source["id"]
    assert revised["parent_job_id"] == source["id"]
    assert revised["revision_scene_id"] == "scene-2"
    assert revised["revision_kind"] == "audio"
    assert revised["status"] == "queued"
    assert revised["current_scene"] == 4
    assert len(revised["scene_results"]) == 4
    assert revised["project"]["scenes"][1]["narration"] == "Eine neue Erzählerzeile"
    assert revised["project"]["voice"] == "Pervin"
    assert revised["project"]["voice_speed"] == 1.1
    assert revised["tts_status"] == "pending"
    assert revised["final_path"] is None


def test_visual_revision_invalidates_only_selected_scene_video(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)

    revised = shorts_studio.create_scene_revision(
        source["id"],
        "scene-3",
        video_prompt="Berlin skyline with autonomous air taxis at blue hour",
    )

    assert revised["revision_kind"] == "video"
    assert revised["current_scene"] == 2
    assert [item["scene_id"] for item in revised["scene_results"]] == [
        "scene-1", "scene-2", "scene-4",
    ]
    assert revised["project"]["scenes"][2]["video_prompt"] == (
        "Berlin skyline with autonomous air taxis at blue hour"
    )


def test_force_regenerate_scene_without_text_change_invalidates_video(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)

    revised = shorts_studio.create_scene_revision(
        source["id"],
        "scene-1",
        force_regenerate_video=True,
    )

    assert revised["revision_kind"] == "video"
    assert revised["current_scene"] == 0
    assert "scene-1" not in {item["scene_id"] for item in revised["scene_results"]}


def test_revision_requires_an_actual_change(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="requires a change"):
        shorts_studio.create_scene_revision(source["id"], "scene-1")
