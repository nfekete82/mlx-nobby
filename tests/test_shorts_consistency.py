import pytest

from agent import shorts_jobs, shorts_studio
from agent.shorts_consistency import (
    consistent_video_job_request,
    keyframe_job_request,
    scene_keyframe_prompt,
)
from agent.shorts_planner import ShortProject, _planning_messages


def project(**changes):
    value = {
        "title": "Berlin 2036",
        "duration": 10,
        "music_enabled": False,
        "consistency_mode": True,
        "character_consistency": True,
        "style_consistency": True,
        "style_strength": 0.85,
        "visual_bible": {
            "style": "cinematic near-future realism",
            "character": "adult presenter, short dark hair, dark smart jacket",
            "environment": "Berlin 2036 with green rooftops and autonomous transit",
            "palette": "cool blue with restrained amber highlights",
            "camera": "vertical cinematic framing, natural lens language",
            "continuity_rules": [
                "Keep the presenter identity and jacket unchanged",
                "Keep architecture grounded and photorealistic",
            ],
        },
        "scenes": [
            {
                "id": "scene-1",
                "duration": 5,
                "narration": "Berlin verändert sich.",
                "video_prompt": "Presenter overlooks Alexanderplatz at blue hour",
            },
            {
                "id": "scene-2",
                "duration": 5,
                "narration": "Mobilität wird autonom.",
                "video_prompt": "Same presenter walks beside an autonomous tram",
            },
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
    job = shorts_jobs.create_short_job(value, chat_id="chat-one", chat_revision=2)
    scene_results = []
    keyframe_results = []
    for index, scene in enumerate(value.scenes, 1):
        image_id = f"170000000{index}-abcdef12345{index}"
        keyframe_results.append({
            "scene_id": scene.id,
            "status": "completed",
            "image_job_id": f"{index:024x}",
            "image_id": image_id,
            "path": f"/images/{image_id}.png",
            "prompt": f"keyframe {index}",
        })
        scene_results.append({
            "scene_id": scene.id,
            "duration": scene.duration,
            "status": "completed",
            "video_job_id": f"{index + 10:024x}",
            "path": f"/videos/{index:024x}.mp4",
            "keyframe_image_id": image_id,
            "keyframe_path": f"/images/{image_id}.png",
        })
    shorts_jobs._update_job(
        job["id"],
        status="running",
        phase="video",
        current_scene=2,
        keyframe_results=keyframe_results,
        scene_results=scene_results,
    )
    return shorts_jobs.get_short_job(job["id"])


def test_legacy_project_default_keeps_old_t2v_runtime():
    value = ShortProject.model_validate({
        "title": "Legacy",
        "duration": 5,
        "scenes": [{
            "id": "scene-1",
            "duration": 5,
            "narration": "Legacy narration",
            "video_prompt": "Legacy visual",
        }],
    })
    assert value.consistency_mode is False


def test_planner_enables_consistency_for_new_multiscene_shorts():
    system = _planning_messages("Erstelle ein 20 Sekunden Short über Berlin")[0]["content"]
    assert "consistency_mode=true" in system
    assert "visual_bible" in system
    assert "style_strength 0.8" in system


def test_keyframe_prompt_contains_persisted_visual_identity():
    value = project()
    prompt = scene_keyframe_prompt(value, value.scenes[1], 1)
    assert "cinematic near-future realism" in prompt
    assert "dark smart jacket" in prompt
    assert "Same presenter walks beside an autonomous tram" in prompt
    assert "85%" in prompt
    assert len(prompt) <= 2000


def test_consistency_requests_use_qwen_keyframe_then_ltx_i2v():
    value = project()
    job = {
        "project": value.model_dump(mode="json"),
        "chat_id": "chat-one",
        "run_id": "run-one",
        "chat_revision": 2,
    }
    image = keyframe_job_request(job, value.scenes[0], 0)
    assert image["operation"] == "generate"
    assert image["payload"]["width"] == 576
    assert image["payload"]["height"] == 1024
    assert image["payload"]["quality"] == "standard"

    video = consistent_video_job_request(
        job,
        value.scenes[0].model_dump(mode="json"),
        "/managed/keyframe.png",
    )
    assert video["operation"] == "i2v"
    assert video["payload"]["first_frame"] == "/managed/keyframe.png"
    assert video["payload"]["resize_mode"] == "cover"
    assert video["payload"]["aspect_ratio"] == "9:16"


def test_narration_revision_reuses_keyframes_and_videos(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)
    revised = shorts_studio.create_scene_revision(
        source["id"], "scene-1", narration="Neue Erzählung"
    )
    assert revised["revision_kind"] == "audio"
    assert len(revised["scene_results"]) == 2
    assert len(revised["keyframe_results"]) == 2


def test_visual_prompt_revision_invalidates_only_scene_keyframe_and_video(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)
    revised = shorts_studio.create_scene_revision(
        source["id"],
        "scene-2",
        video_prompt="Same presenter boards the autonomous tram at sunset",
    )
    assert revised["revision_kind"] == "keyframe"
    assert [item["scene_id"] for item in revised["scene_results"]] == ["scene-1"]
    assert [item["scene_id"] for item in revised["keyframe_results"]] == ["scene-1"]
    assert revised["current_scene"] == 1


def test_video_only_regeneration_keeps_existing_keyframe(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)
    revised = shorts_studio.create_scene_revision(
        source["id"], "scene-1", force_regenerate_video=True
    )
    assert revised["revision_kind"] == "video"
    assert [item["scene_id"] for item in revised["scene_results"]] == ["scene-2"]
    assert {item["scene_id"] for item in revised["keyframe_results"]} == {"scene-1", "scene-2"}


def test_keyframe_regeneration_invalidates_keyframe_and_video(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)
    revised = shorts_studio.create_scene_revision(
        source["id"], "scene-1", force_regenerate_keyframe=True
    )
    assert revised["revision_kind"] == "keyframe"
    assert [item["scene_id"] for item in revised["scene_results"]] == ["scene-2"]
    assert [item["scene_id"] for item in revised["keyframe_results"]] == ["scene-2"]


def test_global_consistency_change_invalidates_all_visual_media(tmp_path, monkeypatch):
    source = completed_source(tmp_path, monkeypatch)
    revised = shorts_studio.create_scene_revision(
        source["id"], "scene-1", style_strength=0.55
    )
    assert revised["revision_kind"] == "consistency"
    assert revised["scene_results"] == []
    assert revised["keyframe_results"] == []
    assert revised["current_scene"] == 0


def test_keyframe_regeneration_requires_consistency_mode(tmp_path, monkeypatch):
    configure_store(tmp_path, monkeypatch)
    legacy = project(consistency_mode=False, visual_bible=None)
    job = shorts_jobs.create_short_job(legacy, chat_id="chat-one")
    with pytest.raises(ValueError, match="requires consistency mode"):
        shorts_studio.create_scene_revision(
            job["id"], "scene-1", force_regenerate_keyframe=True
        )
