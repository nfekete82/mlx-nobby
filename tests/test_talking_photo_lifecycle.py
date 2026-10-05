from pathlib import Path

from agent import media_lifecycle, talking_photo, talking_photo_lifecycle


def _storage(monkeypatch, tmp_path):
    tp_root = tmp_path / "talking-photo"
    monkeypatch.setattr(talking_photo, "ROOT", tp_root)
    monkeypatch.setattr(talking_photo, "JOBS", tp_root / "jobs")
    monkeypatch.setattr(talking_photo, "OUTPUT", tp_root / "videos")
    talking_photo.JOBS.mkdir(parents=True)
    talking_photo.OUTPUT.mkdir(parents=True)

    lifecycle_root = tmp_path / "mlx-web"
    state = lifecycle_root / "media-lifecycle"
    monkeypatch.setattr(media_lifecycle, "ROOT", lifecycle_root)
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", state)
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", state / "assets.json")
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", lifecycle_root / "images")
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", lifecycle_root / "videos")
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_ROOT", talking_photo.OUTPUT)
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_WORK_ROOT", tp_root / "work")
    monkeypatch.setattr(media_lifecycle, "BATCH_UPLOAD_ROOT", lifecycle_root / "batch" / "uploads")
    return tp_root


def _completed(job_id):
    return {
        "id": job_id,
        "kind": "talking_photo",
        "status": "completed",
        "phase": "completed",
        "result": {"video_url": f"/api/talking-photo/videos/{job_id}"},
        "saved": False,
    }


def test_completed_job_is_registered_temporary(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "a" * 24
    talking_photo._write_job(_completed(job_id))
    (talking_photo.OUTPUT / f"{job_id}.mp4").write_bytes(b"video")

    job = talking_photo_lifecycle.get_job(job_id)

    assert job["temporary"] is True
    assert media_lifecycle.status()["temporary"] == 1


def test_keep_job_promotes_video_and_protects_it(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "b" * 24
    talking_photo._write_job(_completed(job_id))
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    path.write_bytes(b"video")

    kept = talking_photo_lifecycle.keep_job(job_id)
    discarded = talking_photo_lifecycle.discard_job(job_id)

    assert kept["persistent"] is True
    assert discarded["persistent"] is True
    assert path.is_file()
    assert talking_photo.get_job(job_id)["saved"] is True


def test_discard_completed_job_deletes_video_and_metadata(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "c" * 24
    talking_photo._write_job(_completed(job_id))
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    path.write_bytes(b"video")
    talking_photo_lifecycle.get_job(job_id)

    result = talking_photo_lifecycle.discard_job(job_id)

    assert result["status"] == "discarded"
    assert result["deleted"] is True
    assert not path.exists()
    assert not talking_photo._job_file(job_id).exists()


def test_discard_active_job_requests_cancellation(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "d" * 24
    talking_photo._write_job({
        "id": job_id,
        "kind": "talking_photo",
        "status": "tts",
        "phase": "tts",
        "cancel_requested": False,
    })

    result = talking_photo_lifecycle.discard_job(job_id)

    assert result["status"] == "cancelling"
    assert talking_photo.get_job(job_id)["cancel_requested"] is True
