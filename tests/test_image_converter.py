"""Offline tests for converter functionality and HTTP contract."""
from io import BytesIO
from zipfile import ZipFile
import json

from PIL import Image
from fastapi.testclient import TestClient

from backend.app import app
from backend.image_converter import convert_bytes, clean_name


def sample():
    im = Image.new("RGBA", (80, 60), (220, 25, 12, 100))
    out = BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def test_conversion_and_safe_names():
    assert clean_name("../../unsafe.png") == "unsafe.png"
    assert clean_name("..\\..\\unsafe.png") == "unsafe.png"
    jpg = Image.open(BytesIO(convert_bytes(sample(), "input.png", "JPEG", 85, 40)))
    assert jpg.format == "JPEG" and jpg.size == (40, 30) and jpg.mode == "RGB"
    png = Image.open(BytesIO(convert_bytes(sample(), "input.png", "PNG")))
    assert png.mode == "RGBA" and png.getpixel((0, 0))[3] == 100


def test_batch_zip_duplicate_names_and_rejected_images():
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/image-converter/batch", data={"fmt": "WEBP"},
            files=[("files", ("same.png", sample(), "image/png")),
                   ("files", ("same.png", sample(), "image/png")),
                   ("files", ("bad.png", b"not a png", "image/png"))])
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert "same.webp" in archive.namelist()
        assert "same-2.webp" in archive.namelist()
        report = json.loads(archive.read("conversion-report.json"))
        assert [row["status"] for row in report] == ["ok", "ok", "error"]


def test_batch_limits():
    with TestClient(app, base_url="http://localhost") as client:
        too_large = client.post("/api/image-converter/batch",
            files=[("files", ("large.png", b"x" * (18 * 1024 * 1024 + 1), "image/png"))])
        invalid = client.post("/api/image-converter/batch", data={"fmt": "GIF"},
            files=[("files", ("small.png", sample(), "image/png"))])
    assert too_large.status_code == 413
    assert invalid.status_code == 422
