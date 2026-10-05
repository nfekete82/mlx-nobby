from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import media_lifecycle_routes


def test_lifecycle_routes_persist_and_discard(monkeypatch):
    app = FastAPI()
    persisted = []
    discarded = []
    monkeypatch.setattr(
        media_lifecycle_routes.media_lifecycle,
        "persist",
        lambda kind, asset_id: persisted.append((kind, asset_id)) or {"persistent": True},
    )
    monkeypatch.setattr(
        media_lifecycle_routes.media_lifecycle,
        "discard_many",
        lambda items: discarded.extend(items) or {"processed": len(items), "deleted": len(items)},
    )
    media_lifecycle_routes.install_routes(app)
    client = TestClient(app)

    response = client.post(
        "/api/media-lifecycle/persist",
        json={"assets": [{"kind": "video", "id": "a" * 24}]},
    )
    assert response.status_code == 200
    assert persisted == [("video", "a" * 24)]

    response = client.post(
        "/api/media-lifecycle/discard",
        json={"assets": [{"kind": "image", "id": "1234567890-abcdef123456"}]},
    )
    assert response.status_code == 200
    assert discarded == [{"kind": "image", "id": "1234567890-abcdef123456"}]


def test_download_middleware_promotes_asset(monkeypatch):
    app = FastAPI()
    promoted = []
    monkeypatch.setattr(
        media_lifecycle_routes.media_lifecycle,
        "persist",
        lambda kind, asset_id: promoted.append((kind, asset_id)) or {"persistent": True},
    )

    @app.get("/api/images/{image_id}")
    def image(image_id: str):
        return {"id": image_id}

    app.add_middleware(media_lifecycle_routes.MediaLifecycleDownloadMiddleware)
    client = TestClient(app)
    asset_id = "1234567890-abcdef123456"

    assert client.get(f"/api/images/{asset_id}").status_code == 200
    assert promoted == []

    assert client.get(f"/api/images/{asset_id}?download=1").status_code == 200
    assert promoted == [("image", asset_id)]


def test_download_middleware_supports_video_and_talking_photo(monkeypatch):
    app = FastAPI()
    promoted = []
    monkeypatch.setattr(
        media_lifecycle_routes.media_lifecycle,
        "persist",
        lambda kind, asset_id: promoted.append((kind, asset_id)) or {"persistent": True},
    )

    @app.get("/api/videos/{asset_id}")
    def video(asset_id: str):
        return {"id": asset_id}

    @app.get("/api/talking-photo/videos/{asset_id}")
    def talking(asset_id: str):
        return {"id": asset_id}

    app.add_middleware(media_lifecycle_routes.MediaLifecycleDownloadMiddleware)
    client = TestClient(app)

    client.get("/api/videos/" + "b" * 24 + "?download=true")
    client.get("/api/talking-photo/videos/" + "c" * 24 + "?download=1")

    assert promoted == [("video", "b" * 24), ("talking_photo", "c" * 24)]
