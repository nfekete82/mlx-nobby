"""CPU-only security and workflow regression tests for the local image converter."""
from __future__ import annotations

from io import BytesIO
import time
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend import image_converter_routes as converter


@pytest.fixture
def client():
    app = FastAPI()
    converter.install_routes(app)
    client = TestClient(app)
    existing = set(converter._jobs)
    yield client
    for job_id in set(converter._jobs) - existing:
        job = converter._jobs.pop(job_id)
        job["cancel"].set()
        converter._owned_dirs.discard(job["directory"])
        # The test waits for a terminal status before cleaning completed dirs.
        if job["status"] in {"complete", "failed", "cancelled"}:
            import shutil
            shutil.rmtree(job["directory"], ignore_errors=True)


def png_bytes(*, mode="RGBA", size=(48, 36), exif=None):
    stream = BytesIO()
    color = (220, 45, 65, 60) if mode == "RGBA" else (220, 45, 65)
    image = Image.new(mode, size, color)
    options = {"exif": exif} if exif else {}
    image.save(stream, "PNG", **options)
    return stream.getvalue()


def await_final(client, job_id):
    for _ in range(200):
        response = client.get(f"/api/converter/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"complete", "failed", "cancelled"}:
            return job
        time.sleep(0.03)
    raise AssertionError("Image conversion did not finish")


def post(client, entries, **options):
    payload = [("files", (name, content, "application/octet-stream")) for name, content in entries]
    return client.post("/api/converter/jobs", files=payload,
                       data={"target": "webp", **{k: str(v) for k, v in options.items()}})


def test_batch_zip_individual_download_dimensions_and_duplicate_names(client):
    first = png_bytes()
    second = png_bytes(mode="RGB", size=(240, 120))
    response = post(client, [("picture.png", first), ("picture.png", second)],
                    target="jpg", quality=87, max_dimension=100)
    assert response.status_code == 202, response.text
    job = await_final(client, response.json()["id"])
    assert job["status"] == "complete"
    assert job["processed"] == job["total"] == 2
    assert [f["output"] for f in job["files"]] == ["picture.jpg", "picture-2.jpg"]
    assert job["files"][1]["width"] == 100
    assert job["files"][1]["height"] == 50
    assert job["files"][0]["bytes_before"] == len(first)
    assert job["files"][0]["bytes_after"] > 0
    archive_response = client.get(f"/api/converter/jobs/{job['id']}/download")
    assert archive_response.status_code == 200
    assert archive_response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(archive_response.content)) as z:
        assert set(z.namelist()) == {"picture.jpg", "picture-2.jpg", "ergebnisse.json"}
        with Image.open(BytesIO(z.read("picture.jpg"))) as result:
            assert result.format == "JPEG"
            assert result.mode == "RGB"
    individual = client.get(f"/api/converter/jobs/{job['id']}/files/1")
    assert individual.status_code == 200
    assert individual.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/converter/jobs/{job['id']}/files/2").status_code == 404


def test_transparent_png_to_jpg_background_and_metadata_removed(client):
    exif = Image.Exif()
    exif[270] = "Sensitive description"
    source = png_bytes(exif=exif.tobytes())
    response = post(client, [("alpha.png", source)], target="jpg",
                    background="#00ff00", strip_metadata="true")
    assert response.status_code == 202
    job = await_final(client, response.json()["id"])
    image_response = client.get(f"/api/converter/jobs/{job['id']}/files/0")
    with Image.open(BytesIO(image_response.content)) as converted:
        assert converted.mode == "RGB"
        color = converted.getpixel((0, 0))
        assert color[1] > color[0] and color[1] > color[2]
        assert converted.getexif().get(270) is None


def test_untrusted_names_ignored_and_unreadable_files_reported(client):
    response = post(client, [("../../confidential.png", png_bytes()),
                             ("broken.png", b"this is not actually an image")],
                    target="webp")
    assert response.status_code == 202
    job = await_final(client, response.json()["id"])
    assert job["status"] == "complete"
    assert job["files"][0]["source"] == "confidential.png"
    assert job["files"][1]["status"] == "failed"
    assert "confidential.webp" == job["files"][0]["output"]
    archive = client.get(f"/api/converter/jobs/{job['id']}/download")
    with zipfile.ZipFile(BytesIO(archive.content)) as z:
        assert "confidential.webp" in z.namelist()
        assert not any(".." in name or name.startswith("/") for name in z.namelist())


def test_all_unreadable_fails_closed_and_zip_is_not_served(client):
    response = post(client, [("fake.jpg", b"wrong")])
    assert response.status_code == 202
    job = await_final(client, response.json()["id"])
    assert job["status"] == "failed"
    assert job["files"][0]["status"] == "failed"
    assert client.get(f"/api/converter/jobs/{job['id']}/download").status_code == 409


def test_upload_size_limits_and_input_validation(client, monkeypatch):
    assert post(client, [("bad.svg", b"<svg/>")]).status_code == 422
    assert post(client, [("ok.png", png_bytes())], target="unknown").status_code == 422
    assert post(client, [("ok.png", png_bytes())], background="red").status_code == 422
    assert post(client, [("ok.png", png_bytes())], quality=1).status_code == 422
    monkeypatch.setattr(converter, "MAX_FILE_BYTES", 8)
    assert post(client, [("over.png", png_bytes())]).status_code == 413


def test_pixel_limit_and_status_lookup(client, monkeypatch):
    monkeypatch.setattr(converter, "MAX_PIXELS", 10)
    response = post(client, [("large.png", png_bytes())])
    job = await_final(client, response.json()["id"])
    assert job["status"] == "failed"
    assert job["files"][0]["status"] == "failed"
    assert client.get("/api/converter/jobs/" + "a" * 32).status_code == 404


def test_cancel_queued_job_and_format_capabilities(client):
    caps = client.get("/api/converter/capabilities").json()
    assert caps["max_files"] == 100
    assert set(caps["output_formats"]) == {"jpg", "png", "webp", "avif"}
    response = post(client, [("photo.png", png_bytes())])
    assert response.status_code == 202
    job_id = response.json()["id"]
    result = client.post(f"/api/converter/jobs/{job_id}/cancel")
    assert result.status_code == 200
    job = await_final(client, job_id)
    assert job["status"] in {"complete", "cancelled"}


def test_frontend_and_version_remain_release_safe():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend/converter.html").read_text()
    script = (root / "frontend/assets/converter.js").read_text()
    chat = (root / "frontend/chat.html").read_text()
    assert 'id="dropZone"' in html and 'id="downloadAll"' in html
    assert "/api/converter/jobs" in script
    assert 'href="/converter"' in chat
    assert (root / "VERSION").read_text().strip() == "1.19.0"
    assert "local image converter" in (root / "CHANGELOG.md").read_text()
