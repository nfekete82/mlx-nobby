"""Local metadata search and details: never expose paths or invent provenance."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import media_lifecycle, media_library_routes, media_library_previews


IMAGE = "1791579990-f04fe5195fe0"
LEGACY = "1791579990-aaaaaaaaaaaa"
VIDEO = "a" * 24
ACCEPTANCE = "b" * 24


@pytest.fixture
def library(monkeypatch, tmp_path):
    roots = {kind: tmp_path / kind for kind in media_library_routes.KINDS}
    for path in roots.values():
        path.mkdir()
    monkeypatch.setattr(media_lifecycle, "ROOT", tmp_path)
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", roots["image"])
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", roots["video"])
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_ROOT", roots["talking_photo"])
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", tmp_path / "lifecycle")
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", tmp_path / "lifecycle" / "assets.json")
    (roots["image"] / (IMAGE + ".png")).write_bytes(b"image-data")
    (roots["image"] / (LEGACY + ".png")).write_bytes(b"legacy")
    (roots["video"] / (VIDEO + ".mp4")).write_bytes(b"video-data")
    (roots["video"] / (ACCEPTANCE + ".mp4")).write_bytes(b"fixture")
    media_lifecycle.register("video", ACCEPTANCE, owner="acceptance")
    queue = tmp_path / "media-queue"
    queue.mkdir()
    (queue / "jobs.json").write_text(json.dumps({
        "c" * 24: {
            "status": "completed", "kind": "image",
            "request": {"payload": {"prompt": "Blue mountain forest"}},
            "result": {
                "id": IMAGE, "prompt": "Blue mountain forest",
                "model": "Juggernaut-XI", "width": 1024, "height": 768,
                "source_path": "/private/do-not-expose", "provider": "mflux",
            },
        }
    }))
    jobs = tmp_path / "video-jobs"
    jobs.mkdir()
    (jobs / ("d" * 24 + ".json")).write_text(json.dumps({
        "status": "completed",
        "result": {"id": VIDEO, "prompt": "Sunrise above ocean",
                   "model": "ltx-video", "path": "/private/raw/secret.mp4"}
    }))
    app = FastAPI()
    media_library_routes.install_routes(app)
    return TestClient(app)


def test_search_matches_prompts_models_and_casefold_without_paths(library):
    response = library.get("/api/library/search?q=BLUE%20mountain")
    assert response.status_code == 200
    results = response.json()
    assert results["total"] == 1
    assert results["assets"][0]["id"] == IMAGE
    assert results["assets"][0]["model"] == "Juggernaut-XI"
    assert "path" not in str(results).lower()
    assert "do-not-expose" not in str(results)
    assert library.get("/api/library/search?q=ltx-video").json()["total"] == 1
    assert library.get("/api/library/search?q=missing").json()["total"] == 0
    assert library.get("/api/library/search?q=blue&kind=video").json()["total"] == 0


def test_legacy_media_is_visible_without_invented_prompt(library):
    response = library.get("/api/library/assets?limit=100")
    assert response.status_code == 200
    assets = response.json()["assets"]
    assert {a["id"] for a in assets} == {IMAGE, LEGACY, VIDEO}
    legacy = next(asset for asset in assets if asset["id"] == LEGACY)
    assert "prompt" not in legacy and "model" not in legacy
    assert ACCEPTANCE not in str(assets)


def test_details_validate_canonical_media_and_return_only_safe_fields(library, monkeypatch):
    monkeypatch.setattr(media_library_previews, "metadata",
                        lambda kind, asset_id: {"id": asset_id, "width": 1280,
                                               "height": 720, "duration_seconds": 8.5,
                                               "path": "/hidden/preview.mp4"})
    response = library.get(f"/api/library/assets/video/{VIDEO}/details")
    assert response.status_code == 200
    info = response.json()
    assert info["prompt"] == "Sunrise above ocean"
    assert info["duration_seconds"] == 8.5
    assert info["width"] == 1280
    assert "path" not in info and "/hidden" not in str(info)
    assert library.get(f"/api/library/assets/video/{ACCEPTANCE}/details").status_code == 404
    assert library.get("/api/library/assets/image/../../details").status_code in (404, 405)
    assert library.get("/api/library/assets/video/not-an-id/details").status_code == 404


def test_search_input_is_bounded(library):
    assert library.get("/api/library/search", params={"q": "a" * 201}).status_code == 422
    assert library.get("/api/library/search?limit=501").status_code == 422
    assert library.get("/api/library/search?kind=nonexistent").status_code == 422
