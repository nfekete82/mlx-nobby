"""Media Library 3.0 persistent favorites / collection isolation and security."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import media_lifecycle, media_library_organize as org, media_library_routes


@pytest.fixture
def media_setup(monkeypatch, tmp_path):
    roots = {kind: tmp_path / kind for kind in ("image", "video", "talking_photo")}
    for root in roots.values():
        root.mkdir()
    state = tmp_path / "metadata"
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", state)
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", state / "assets.json")
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", roots["image"])
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", roots["video"])
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_ROOT", roots["talking_photo"])
    image_id = "1791579990-f04fe5195fe0"
    video_id = "a" * 24
    talking_id = "b" * 24
    (roots["image"] / f"{image_id}.png").write_bytes(b"image")
    (roots["video"] / f"{video_id}.mp4").write_bytes(b"movie")
    (roots["talking_photo"] / f"{talking_id}.mp4").write_bytes(b"talking movie")
    return roots, image_id, video_id, talking_id


def test_favorites_persist_across_calls_without_media_copies(media_setup):
    roots, image_id, video_id, talking_id = media_setup
    collection = org.create_collection("Meine besten Videos")
    result = org.update_many(
        [{"kind": "image", "id": image_id}, {"kind": "talking_photo", "id": talking_id}],
        "favorite",
    )
    assert result["updated"] == 2
    org.update_many([{"kind": "talking_photo", "id": talking_id}], "add_collection", collection["id"])
    assert org.snapshot()["favorites"] == ["image:" + image_id, "talking_photo:" + talking_id]
    assert org.snapshot()["collections"][0]["items"] == ["talking_photo:" + talking_id]
    assert org._file().is_file()
    assert media_lifecycle.status()["persistent"] == 2
    assert len(list(roots["image"].iterdir())) == 1
    assert len(list(roots["talking_photo"].iterdir())) == 1
    assert len(list(roots["video"].iterdir())) == 1
    org.update_many([{"kind": "image", "id": image_id}], "unfavorite")
    assert org.snapshot()["favorites"] == ["talking_photo:" + talking_id]


def test_delete_collection_does_not_delete_media(media_setup):
    roots, _, video_id, _ = media_setup
    entry = org.create_collection("Samples")
    org.update_many([{"kind": "video", "id": video_id}], "add_collection", entry["id"])
    assert org.delete_collection(entry["id"])["media_deleted"] is False
    assert org.snapshot()["collections"] == []
    assert (roots["video"] / f"{video_id}.mp4").is_file()


def test_invalid_and_acceptance_assets_cannot_be_favorited(media_setup, tmp_path):
    roots, _, video_id, _ = media_setup
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    (roots["video"] / ("c" * 24 + ".mp4")).symlink_to(outside)
    media_lifecycle.register("video", video_id, owner="acceptance")
    for items in (
        [{"kind": "video", "id": video_id}],
        [{"kind": "video", "id": "c" * 24}],
        [{"kind": "video", "id": "../foo"}],
        [{"kind": "video", "id": "f" * 24}],
    ):
        with pytest.raises(ValueError):
            org.update_many(items, "favorite")
    assert org.snapshot()["favorites"] == []
    assert outside.read_bytes() == b"private"
    with pytest.raises(ValueError):
        org.create_collection("x" * 61)
    with pytest.raises(ValueError):
        org.create_collection("bad\nname")


def test_batch_validation_is_atomic_on_missing_items(media_setup):
    _, image_id, _, _ = media_setup
    with pytest.raises(ValueError):
        org.update_many([
            {"kind": "image", "id": image_id},
            {"kind": "video", "id": "d" * 24},
        ], "favorite")
    assert org.snapshot()["favorites"] == []
    assert media_lifecycle.status()["tracked"] == 0
    with pytest.raises(ValueError):
        org.update_many([{"kind": "image", "id": image_id}] * 101, "favorite")


def test_deleting_media_prunes_organization_and_retains_other_media(media_setup):
    roots, image_id, video_id, _ = media_setup
    collection = org.create_collection("Vorher / Nachher")
    assets = [{"kind": "image", "id": image_id}, {"kind": "video", "id": video_id}]
    org.update_many(assets, "favorite")
    org.update_many(assets, "add_collection", collection["id"])
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    response = client.delete(f"/api/library/assets/image/{image_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    snapshot = org.snapshot()
    assert snapshot["favorites"] == ["video:" + video_id]
    assert snapshot["collections"][0]["items"] == ["video:" + video_id]
    assert not (roots["image"] / f"{image_id}.png").exists()
    assert (roots["video"] / f"{video_id}.mp4").is_file()


def test_api_filters_and_collection_actions(media_setup):
    _, image_id, video_id, _ = media_setup
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    assert client.get("/api/library/organize").json() == org._empty()
    created = client.post("/api/library/organize/collections", json={"name": "Picks"})
    assert created.status_code == 200
    cid = created.json()["id"]
    items = [{"kind": "image", "id": image_id}, {"kind": "video", "id": video_id}]
    add = client.post("/api/library/organize/batch", json={
        "items": items, "operation": "add_collection", "collection_id": cid,
    })
    assert add.status_code == 200, add.text
    assert len(client.get("/api/library/organize").json()["collections"][0]["items"]) == 2
    assert client.post("/api/library/organize/batch", json={
        "items": items, "operation": "add_collection", "collection_id": "bad",
    }).status_code == 422
    assert client.delete("/api/library/organize/collections/" + cid).status_code == 200
    assert client.get("/api/library/organize").json()["collections"] == []


def test_organization_ignores_stale_media_after_ttl_cleanup(media_setup):
    roots, _, video_id, _ = media_setup
    org.update_many([{"kind": "video", "id": video_id}], "favorite")
    (roots["video"] / f"{video_id}.mp4").unlink()
    assert org.snapshot()["favorites"] == []
