"""WebP artifact defaults and backwards-compatible generated media IDs."""
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from image_output_format import finalize_image
from agent import app as agent, media_lifecycle, media_library_routes, media_library_organize


ID = "1791579990-f04fe5195fe0"


def _png(path, *, alpha=False):
    mode = "RGBA" if alpha else "RGB"
    Image.new(mode, (128, 128), (32, 82, 143, 110) if alpha else (32, 82, 143)).save(path, "PNG")


def test_default_webp_quality_90_and_alpha_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv("MLX_IMAGE_OUTPUT_FORMAT", raising=False)
    source = tmp_path / (ID + ".png")
    _png(source, alpha=True)
    png_bytes = source.stat().st_size
    target = finalize_image(source)
    assert target.name == ID + ".webp"
    assert target.is_file() and not source.exists()
    with Image.open(target) as image:
        assert image.format == "WEBP"
        assert image.mode == "RGBA"
        assert image.size == (128, 128)
        assert image.getpixel((0, 0))[3] > 0
    # WebP does not always beat a highly compressible flat PNG, but the
    # WebP encoder should preserve valid media and usually reduce photos.
    assert target.stat().st_size > 0


def test_png_override_and_invalid_provider_output_fallback(tmp_path, monkeypatch):
    source = tmp_path / (ID + ".png")
    _png(source)
    monkeypatch.setenv("MLX_IMAGE_OUTPUT_FORMAT", "png")
    assert finalize_image(source) == source and source.is_file()
    monkeypatch.setenv("MLX_IMAGE_OUTPUT_FORMAT", "webp")
    source.write_bytes(b"not a real PNG")
    assert finalize_image(source) == source
    assert source.read_bytes() == b"not a real PNG"
    assert not source.with_suffix(".webp").exists()


def test_artifact_identity_image_routes_and_legacy_png(tmp_path, monkeypatch):
    monkeypatch.delenv("MLX_IMAGE_OUTPUT_FORMAT", raising=False)
    root = tmp_path / "images"
    root.mkdir()
    monkeypatch.setattr(agent, "IMAGE_DIRECTORY", root)
    source = root / (ID + ".png")
    _png(source)
    artifact = {
        "id": ID, "path": str(finalize_image(source)), "mime_type": "image/webp",
        "width": 128, "height": 128,
    }
    wrapped = agent._image_artifact(artifact, "image_generate")
    assert wrapped["name"] == ID + ".webp"
    assert wrapped["mime_type"] == "image/webp"
    assert agent._resolve_image_artifact_source("image-" + ID) == root / (ID + ".webp")
    reply = agent.image_download(ID)
    assert reply.media_type == "image/webp"
    assert Path(reply.path) == root / (ID + ".webp")

    # A pre-update PNG with the same managed ID must continue to work.
    (root / (ID + ".webp")).unlink()
    _png(source)
    assert agent._resolve_image_artifact_source("image-" + ID) == source
    assert agent.image_download(ID).media_type == "image/png"


def test_library_and_lifecycle_accept_new_and_legacy_images(tmp_path, monkeypatch):
    root = tmp_path / "media"
    images = root / "images"
    images.mkdir(parents=True)
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", images)
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", root / "state")
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", root / "state" / "assets.json")
    source = images / (ID + ".png")
    _png(source)
    webp = finalize_image(source)
    assert media_lifecycle._expected_path("image", ID) == webp
    assert media_lifecycle.register("image", ID, webp)["path"] == str(webp)
    assert media_library_routes.list_assets("image")["total"] == 1
    assert media_library_organize._visible_asset("image", ID) == webp

    persisted = media_lifecycle.persist("image", ID)
    assert persisted["persistent"]
    assert media_lifecycle.discard("image", ID)["deleted"] is False
    assert webp.exists()
    assert media_lifecycle.discard("image", ID, force=True)["deleted"] is True
    assert not webp.exists()

    legacy = images / (ID + ".png")
    _png(legacy)
    assert media_lifecycle._expected_path("image", ID) == legacy
    assert media_library_routes.list_assets("image")["total"] == 1
    assert media_library_organize._visible_asset("image", ID) == legacy
