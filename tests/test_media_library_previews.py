"""Security, lazy video previews, engine metadata, and cache regressions."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import media_library_previews as previews, media_lifecycle, media_library_routes


@pytest.fixture
def video_fixture(monkeypatch, tmp_path):
    roots = {"video": tmp_path / "video", "talking_photo": tmp_path / "talking-photo"}
    for root in roots.values():
        root.mkdir()
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    state = tmp_path / "state"
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", roots["video"])
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_ROOT", roots["talking_photo"])
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_JOBS_ROOT", jobs)
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", state)
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", state / "assets.json")
    monkeypatch.setattr(previews, "CACHE_ROOT", tmp_path / "thumbs")
    previews._probe.cache_clear()
    return roots, jobs, tmp_path


def test_video_previews_require_managed_canonical_files(video_fixture):
    roots, jobs, tmp = video_fixture
    good = roots["video"] / ("a" * 24 + ".mp4")
    good.write_bytes(b"video")
    path, stat = previews.media_file("video", "a" * 24)
    assert path == good and stat.st_size == 5
    with pytest.raises(ValueError):
        previews.media_file("image", "a" * 24)
    with pytest.raises(ValueError):
        previews.media_file("video", "../bad")
    with pytest.raises(FileNotFoundError):
        previews.media_file("video", "b" * 24)
    outside = tmp / "outside.mp4"
    outside.write_bytes(b"secret")
    (roots["video"] / ("b" * 24 + ".mp4")).symlink_to(outside)
    with pytest.raises(FileNotFoundError):
        previews.media_file("video", "b" * 24)


def test_metadata_reads_real_duration_and_completed_talking_photo_engine(video_fixture, monkeypatch):
    roots, jobs, _ = video_fixture
    job_id = "b" * 24
    (roots["talking_photo"] / (job_id + ".mp4")).write_bytes(b"mp4")
    (jobs / (job_id + ".json")).write_text(json.dumps({
        "status": "completed",
        "result": {"engine": "ltx-distilled"},
    }))
    class Result:
        stdout = '{"streams":[{"width":640,"height":640,"duration":"27.430"}]}'
    with patch.object(previews.shutil, "which", return_value="/bin/ffprobe"), \
         patch.object(previews.subprocess, "run", return_value=Result()) as run:
        metadata = previews.metadata("talking_photo", job_id)
    assert metadata["engine"] == "ltx-distilled"
    assert metadata["duration_seconds"] == 27.43
    assert metadata["width"] == 640
    assert metadata["height"] == 640
    assert run.call_args.kwargs["timeout"] == 12
    listing = media_library_routes.list_assets("video")
    assert listing["assets"][0]["engine"] == "ltx-distilled"
    assert "path" not in listing["assets"][0]


def test_thumbnail_is_cached_and_purged_with_no_video_copy(video_fixture, monkeypatch):
    roots, jobs, tmp = video_fixture
    job_id = "c" * 24
    video = roots["video"] / (job_id + ".mp4")
    video.write_bytes(b"original video bytes")
    invocations = []
    class Result:
        returncode = 0
        stderr = ""
    def write_jpeg(command, **kwargs):
        invocations.append(command)
        target = Path(command[-1])
        target.write_bytes(bytes((255, 216)) + bytes(300) + bytes((255, 217)))
        return Result()
    with patch.object(previews.shutil, "which", return_value="/bin/ffmpeg"), \
         patch.object(previews.subprocess, "run", side_effect=write_jpeg):
        first = previews.thumbnail("video", job_id)
        second = previews.thumbnail("video", job_id)
    assert first == second and first.is_file()
    assert len(invocations) == 1
    assert invocations[0][-1].endswith(".jpg")
    assert video.read_bytes() == b"original video bytes"
    previews.purge_cached("video", job_id)
    assert not first.exists()
    assert video.read_bytes() == b"original video bytes"


def test_unavailable_thumbnail_returns_503_and_missing_file_returns_404(video_fixture, monkeypatch):
    roots, _, _ = video_fixture
    video_id = "d" * 24
    (roots["video"] / (video_id + ".mp4")).write_bytes(b"video")
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    assert client.get("/api/library/assets/video/" + "e" * 24 + "/thumbnail").status_code == 404
    assert client.get("/api/library/assets/image/" + video_id + "/metadata").status_code == 404
    with patch.object(previews.shutil, "which", return_value=None):
        assert client.get("/api/library/assets/video/" + video_id + "/thumbnail").status_code == 503


def test_acceptance_media_cannot_expose_metadata_or_thumbnails(video_fixture):
    roots, _, _ = video_fixture
    job_id = "f" * 24
    path = roots["video"] / (job_id + ".mp4")
    path.write_bytes(b"test video")
    media_lifecycle.register("video", job_id, path, owner="acceptance")
    app = FastAPI()
    media_library_routes.install_routes(app)
    client = TestClient(app)
    assert client.get("/api/library/assets/video/" + job_id + "/metadata").status_code == 404
    assert client.get("/api/library/assets/video/" + job_id + "/thumbnail").status_code == 404
