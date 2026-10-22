"""Regression tests for managed, user-selected Shorts scene frames and voices."""
import base64
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import (shorts_scene_images, shorts_jobs, shorts_drafts,
                   shorts_draft_routes, shorts_consistency_runtime)
from agent.shorts_planner import ShortProject
from agent.shorts_preflight import preflight_project


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "shorts"
    monkeypatch.setattr(shorts_jobs, "SHORTS_DIRECTORY", root)
    monkeypatch.setattr(shorts_jobs, "SHORTS_JOBS_FILE", root / "jobs.json")
    monkeypatch.setattr(shorts_jobs, "MUSIC_DIRECTORY", tmp_path / "music")
    monkeypatch.setattr(shorts_scene_images, "image_directory", lambda: tmp_path / "images")
    with shorts_jobs._workers_lock:
        shorts_jobs._workers.clear()
    return root


def image_data(color="gold"):
    file = BytesIO()
    Image.new("RGB", (128, 192), color).save(file, "PNG")
    return base64.b64encode(file.getvalue()).decode()


def short_data(image_id):
    return {
        "schema_version": 2, "title": "Venus", "duration": 5,
        "consistency_mode": True, "music_enabled": False,
        "voice": "lana_weiss", "cast": [],
        "scenes": [{
            "id": "venus", "duration": 5,
            "scene_image_id": image_id, "video_prompt": "Orbiting Venus",
            "narration": "Willkommen auf der Venus.",
            "voice": "meine_stimme",
        }]
    }


def test_scene_image_upload_is_bounded_managed_and_persisted(store):
    item = shorts_scene_images.upload_image(image_data())
    image_id = item["id"]
    assert shorts_scene_images.image_path(image_id).is_file()
    import video_providers
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(video_providers, "IMAGE_ROOT", shorts_scene_images.image_directory())
        assert video_providers.validate_first_frame(
            shorts_scene_images.image_path(image_id)) == shorts_scene_images.image_path(image_id)
    assert shorts_scene_images.list_images()[0]["id"] == image_id
    with pytest.raises(ValueError):
        shorts_scene_images.image_path("../../secrets")
    with pytest.raises(ValueError):
        shorts_scene_images.upload_image("not valid base64")
    draft = shorts_drafts.save_draft(short_data(image_id))
    restored = shorts_drafts.get_draft(draft["id"])
    assert restored["project"]["scenes"][0]["scene_image_id"] == image_id
    assert restored["project"]["scenes"][0]["voice"] == "meine_stimme"
    project = ShortProject.model_validate(restored["project"])
    assert project.voice_for_scene(project.scenes[0]) == "meine_stimme"
    assert preflight_project(project)["available"] is True


def test_scene_image_api_returns_private_image_and_listing(store):
    app = FastAPI()
    shorts_draft_routes.install_routes(app)
    client = TestClient(app)
    image = client.post("/api/shorts/scene-images",
                        json={"content_base64": image_data()})
    assert image.status_code == 201
    image_id = image.json()["id"]
    data = client.get("/api/shorts/scene-images/" + image_id)
    assert data.status_code == 200
    assert data.headers["content-type"].startswith("image/png")
    assert client.get("/api/shorts/scene-images").json()["images"][0]["id"] == image_id
    assert client.get("/api/shorts/scene-images/bad").status_code == 400


def test_supplied_frame_reaches_ltx_without_generating_a_qwen_image(store, monkeypatch):
    image_id = shorts_scene_images.upload_image(image_data())["id"]
    project = ShortProject.model_validate(short_data(image_id))
    job = shorts_jobs.create_short_job(project, chat_id="scene-image-test")
    calls = []
    def video_request(method, path, payload=None, timeout=15):
        calls.append((method, path, payload))
        if method == "POST":
            return {"id": "a" * 24}
        return {"status": "failed", "error": "expected stopped test job"}
    def no_image(*args, **kwargs):
        raise AssertionError("user-selected image must not invoke image generator")
    monkeypatch.setattr(shorts_consistency_runtime, "_image_request", no_image)
    shorts_consistency_runtime.run_consistent_short_job(
        job["id"], request_fn=video_request, poll_interval=0,
    )
    submitted = [payload for method, path, payload in calls
                 if method == "POST" and path == "/jobs"]
    assert len(submitted) == 1
    assert submitted[0]["operation"] == "i2v"
    assert submitted[0]["payload"]["first_frame"] == str(shorts_scene_images.image_path(image_id))
    frames = shorts_jobs.get_short_job(job["id"])["keyframe_results"]
    assert frames[0]["source_asset_id"] == image_id


def test_project_with_selected_frame_uses_i2v_and_missing_image_fails_preflight(store):
    first = shorts_scene_images.upload_image(image_data())["id"]
    data = short_data(first)
    data["consistency_mode"] = False
    saved = shorts_drafts.save_draft(data)
    assert saved["project"]["consistency_mode"] is True
    shorts_scene_images.image_path(first).unlink()
    with pytest.raises(ValueError, match="missing"):
        preflight_project(ShortProject.model_validate(saved["project"]))
