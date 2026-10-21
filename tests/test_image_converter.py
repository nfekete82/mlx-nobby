"""Focused codec and HTTP ZIP regression checks; no MLX/model services."""

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.image_converter import ConversionError, convert_image
from backend.image_converter_routes import install_routes


def png_bytes(*, rgba=True):
    raw = BytesIO()
    Image.new("RGBA" if rgba else "RGB", (120, 80),
              (20, 80, 130, 85) if rgba else (20, 80, 130)).save(raw, format="PNG")
    return raw.getvalue()


def test_codec_alpha_orientation_resize_and_invalid_input():
    name, converted, dimensions = convert_image(
        png_bytes(), "test.png", fmt="jpeg", quality=90, max_dimension=256
    )
    assert name == "test.jpg" and dimensions == (120, 80)
    with Image.open(BytesIO(converted)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        assert image.size == (120, 80)
        # RGBA transparency becomes a white composite in JPEG.
        assert image.getpixel((20, 20))[0] > 135
        assert "exif" not in image.info
    webp_name, payload, dims = convert_image(
        png_bytes(), "bild.png", fmt="webp", quality=82
    )
    assert webp_name == "bild.webp" and dims == (120, 80)
    with Image.open(BytesIO(payload)) as image:
        assert image.format == "WEBP" and image.mode == "RGBA"
    try:
        convert_image(b"not an image", "dummy.png", fmt="png")
    except ConversionError:
        pass
    else:
        assert False, "Fake picture must be rejected"


def test_http_batch_zip_handles_duplicates_partial_failures_and_limits(tmp_path):
    app = FastAPI()
    install_routes(app, frontend_dir=Path(__file__).resolve().parents[1] / "frontend")
    client = TestClient(app)
    sample = png_bytes(rgba=False)
    response = client.post(
        "/api/converter/images",
        files=[
            ("files", ("bild.png", sample, "image/png")),
            ("files", ("bild.png", sample, "image/png")),
            ("files", ("broken.png", b"not a picture", "image/png")),
        ],
        data={"format": "webp", "quality": "85", "max_dimension": "0"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-converted-count"] == "2"
    assert response.headers["x-failed-count"] == "1"
    with ZipFile(BytesIO(response.content)) as archive:
        assert {"bild.webp", "bild-2.webp", "konvertierung-bericht.json"} == set(archive.namelist())
        report = json.loads(archive.read("konvertierung-bericht.json"))
        assert len(report["converted"]) == 2 and len(report["errors"]) == 1
        with Image.open(BytesIO(archive.read("bild.webp"))) as result:
            assert result.format == "WEBP"
    too_many = client.post(
        "/api/converter/images",
        files=[("files", (f"{i}.png", sample, "image/png")) for i in range(51)],
    )
    assert too_many.status_code == 422
    assert client.get("/converter").status_code == 200
