"""Generated media library discovers only validated managed files."""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import media_library_routes, media_lifecycle


def test_local_index_filters_kinds_and_ignores_invalid_files(tmp_path):
    roots = {}
    for kind in media_library_routes.KINDS:
        roots[kind] = tmp_path / kind
        roots[kind].mkdir()
    image = roots["image"] / "1791579990-f04fe5195fe0.png"
    image.write_bytes(b"sample")
    video = roots["video"] / ("a" * 24 + ".mp4")
    video.write_bytes(b"video")
    (roots["image"] / "private.png").write_bytes(b"not allowed")
    (roots["image"] / "1791579990-f04fe5195fe1.png").write_bytes(b"")
    with patch.object(media_lifecycle, "_root_for", side_effect=lambda kind: roots[kind]), \
         patch.object(media_lifecycle, "_expected_path",
                      side_effect=lambda kind, asset_id: (roots[kind] / (asset_id + media_library_routes.SUFFIX[kind])).resolve()):
        result = media_library_routes.list_assets()
        assert result["total"] == 2
        assert {asset["kind"] for asset in result["assets"]} == {"image", "video"}
        assert all("path" not in asset for asset in result["assets"])
        assert media_library_routes.list_assets("image")["total"] == 1
        with pytest.raises(ValueError):
            media_library_routes.list_assets("../etc")


def test_library_save_and_delete_require_valid_ids(tmp_path):
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    assert client.get("/api/library/assets?kind=private").status_code == 422
    assert client.get("/api/library/assets?limit=1001").status_code == 422
    assert client.post("/api/library/assets/image/../../save").status_code in (404, 405)
    assert client.delete("/api/library/assets/video/bad").status_code == 422
    with patch.object(media_lifecycle, "persist", return_value={
        "id": "a" * 24, "kind": "video", "persistent": True
    }) as persist:
        result = client.post("/api/library/assets/video/" + "a" * 24 + "/save")
        assert result.status_code == 200 and result.json()["persistent"] is True
        persist.assert_called_once_with("video", "a" * 24)
    with patch.object(media_lifecycle, "discard", return_value={"deleted": True}) as discard:
        result = client.delete("/api/library/assets/video/" + "a" * 24)
        assert result.status_code == 200 and result.json()["deleted"] is True
        discard.assert_called_once_with("video", "a" * 24, force=True)

def test_bulk_delete_requires_confirmation_and_limits_to_managed_media(tmp_path):
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    assert client.post("/api/library/assets/delete-all", json={"kind":"all"}).status_code == 400
    assert client.post("/api/library/assets/delete-all", json={
        "kind":"outside", "confirm":"DELETE_ALL_MEDIA_PERMANENTLY"
    }).status_code == 422
    sample = [{"kind": "image", "id": "1791579990-f04fe5195fe0"},
              {"kind": "video", "id": "a" * 24}]
    with patch.object(media_library_routes, "list_assets", return_value={"assets":sample}) as scan, \
         patch.object(media_lifecycle, "discard", return_value={"deleted":True}) as discard:
        response = client.post("/api/library/assets/delete-all", json={
            "kind":"all", "confirm":"DELETE_ALL_MEDIA_PERMANENTLY"
        })
        assert response.status_code == 200
        assert response.json()["deleted"] == 2
        assert discard.call_count == 2
        scan.assert_called_once_with("all", 1000000)
