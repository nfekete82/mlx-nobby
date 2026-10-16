"""Media Studio 1.16 provenance persistence and strict local path validation."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import media_lifecycle, media_library_workflows as workflow, media_library_routes


@pytest.fixture
def media(monkeypatch, tmp_path):
    roots = {kind: tmp_path / kind for kind in ("image", "video", "talking_photo")}
    for folder in roots.values():
        folder.mkdir()
    state = tmp_path / "state"
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", state)
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", state / "assets.json")
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", roots["image"])
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", roots["video"])
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_ROOT", roots["talking_photo"])
    source = "1791579990-f04fe5195fe0"
    video = "a" * 24
    photo = "b" * 24
    (roots["image"] / f"{source}.png").write_bytes(b"image")
    (roots["video"] / f"{video}.mp4").write_bytes(b"video")
    (roots["talking_photo"] / f"{photo}.mp4").write_bytes(b"talking photo")
    return roots, source, video, photo


def test_links_are_atomic_idempotent_and_recoverable(media):
    roots, source, video, photo = media
    assert workflow.snapshot() == {"version": 1, "links": {}}
    assert workflow.link("image", source, "video", video)["linked"]
    assert workflow.link("image", source, "video", video)["linked"]
    assert workflow.link("image", source, "talking_photo", photo)["linked"]
    assert workflow.snapshot()["links"] == {
        "video:" + video: "image:" + source,
        "talking_photo:" + photo: "image:" + source,
    }
    assert json.loads(workflow._file().read_text())["version"] == 1
    assert (roots["image"] / f"{source}.png").read_bytes() == b"image"
    assert (roots["video"] / f"{video}.mp4").read_bytes() == b"video"
    assert not list(roots["video"].glob("*.png"))


def test_missing_and_unsafe_media_are_rejected(media, tmp_path):
    roots, source, video, photo = media
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"secret")
    (roots["video"] / ("c" * 24 + ".mp4")).symlink_to(outside)
    for args in (
        ("image", source, "video", "c" * 24),
        ("image", source, "video", "d" * 24),
        ("image", "1791579990-aaaaaaaaaaaa", "video", video),
    ):
        with pytest.raises(FileNotFoundError):
            workflow.link(*args)
    for args in (
        ("image", source, "image", source),
        ("talking_photo", photo, "video", video),
        ("image", source, "video", "../out"),
        ("image", source, "video", source),
    ):
        with pytest.raises(ValueError):
            workflow.link(*args)
    assert outside.read_bytes() == b"secret"
    media_lifecycle.register("image", source, owner="acceptance")
    with pytest.raises(FileNotFoundError):
        workflow.link("image", source, "video", video)


def test_explicit_media_delete_prunes_both_edges(media):
    roots, source, video, photo = media
    workflow.link("image", source, "video", video)
    workflow.link("image", source, "talking_photo", photo)
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    deleted = client.delete(f"/api/library/assets/talking_photo/{photo}")
    assert deleted.status_code == 200
    assert workflow.snapshot()["links"] == {"video:" + video: "image:" + source}
    removed = client.delete(f"/api/library/assets/image/{source}")
    assert removed.status_code == 200
    assert workflow.snapshot()["links"] == {}
    assert (roots["video"] / f"{video}.mp4").exists()


def test_workflow_api_rejects_noncanonical_media(media):
    _, source, video, _ = media
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    request = {"source_kind": "image", "source_id": source,
               "output_kind": "video", "output_id": video}
    assert client.post("/api/library/workflows/links", json=request).status_code == 200
    assert client.get("/api/library/workflows").json()["links"] == {
        "video:" + video: "image:" + source
    }
    assert client.post("/api/library/workflows/links", json={
        **request, "output_id": "f" * 24,
    }).status_code == 404
    assert client.post("/api/library/workflows/links", json={
        **request, "source_kind": "video",
    }).status_code == 422


def test_stale_links_are_not_exposed_even_without_cleanup(media):
    roots, source, video, _ = media
    workflow.link("image", source, "video", video)
    (roots["image"] / f"{source}.png").unlink()
    assert workflow.snapshot()["links"] == {}


def test_conflicting_origin_not_overwritten(media):
    roots, source, video, _ = media
    another = "1791579990-aaaaaaaaaaaa"
    (roots["image"] / f"{another}.png").write_bytes(b"image two")
    workflow.link("image", source, "video", video)
    with pytest.raises(ValueError):
        workflow.link("image", another, "video", video)
    assert workflow.snapshot()["links"]["video:" + video] == "image:" + source
