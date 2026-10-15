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
    monkeypatch.setattr(media_lifecycle, "TALKING_PHOTO_JOBS_ROOT", talking_photo.JOBS)
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


def test_completed_job_is_registered_persistent(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "a" * 24
    talking_photo._write_job(_completed(job_id))
    (talking_photo.OUTPUT / f"{job_id}.mp4").write_bytes(b"video")

    job = talking_photo_lifecycle.get_job(job_id)

    assert job["temporary"] is False
    assert media_lifecycle.status()["persistent"] == 1


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


def test_discard_completed_job_does_not_delete_a_saved_library_video(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "c" * 24
    talking_photo._write_job(_completed(job_id))
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    path.write_bytes(b"video")

    result = talking_photo_lifecycle.discard_job(job_id)

    assert result["status"] == "kept"
    assert result["persistent"] is True
    assert path.exists()
    assert talking_photo._job_file(job_id).exists()
    assert media_lifecycle.status()["persistent"] == 1


def test_discard_active_job_requests_cancellation_and_starts_watcher(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "d" * 24
    talking_photo._write_job({
        "id": job_id,
        "kind": "talking_photo",
        "status": "tts",
        "phase": "tts",
        "cancel_requested": False,
    })
    started = []

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append((self.target, self.args, self.daemon, self.name))

    monkeypatch.setattr(talking_photo_lifecycle.threading, "Thread", FakeThread)

    result = talking_photo_lifecycle.discard_job(job_id)

    assert result["status"] == "cancelling"
    assert talking_photo.get_job(job_id)["cancel_requested"] is True
    assert len(started) == 1
    assert started[0][0] is talking_photo_lifecycle._discard_when_terminal
    assert started[0][1] == (job_id,)
    assert started[0][2] is True


def test_completion_registers_video_without_browser_polling(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    job_id = "f" * 24
    talking_photo._write_job({
        "id": job_id, "kind": "talking_photo", "status": "motion",
        "phase": "quality", "result": None,
    })
    path = talking_photo.OUTPUT / f"{job_id}.mp4"
    path.write_bytes(b"video")
    talking_photo._update_job(job_id, status="completed", phase="completed",
                              result={"video_url": f"/api/talking-photo/videos/{job_id}"})
    assert media_lifecycle.status()["persistent"] == 1
    assert path.exists()
    assert talking_photo_lifecycle.get_job(job_id)["temporary"] is False


def test_surviving_talking_photos_are_adopted_before_cleanup(monkeypatch, tmp_path):
    import os
    from agent import media_library_routes
    _storage(monkeypatch, tmp_path)
    survivor = "1" * 24
    accepted = "2" * 24
    source_path = talking_photo.OUTPUT / f"{survivor}.mp4"
    source_path.write_bytes(b"existing original")
    os.utime(source_path, (1, 1))
    other = talking_photo.OUTPUT / f"{accepted}.mp4"
    other.write_bytes(b"fixture")
    media_lifecycle.register("talking_photo", accepted, other,
                             owner="acceptance", persistent=False)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"external")
    (talking_photo.OUTPUT / ("3" * 24 + ".mp4")).symlink_to(outside)
    assert media_lifecycle.retain_existing_talking_photos() == 1
    assert media_lifecycle.retain_existing_talking_photos() == 1  # idempotent
    assert media_lifecycle.status()["persistent"] == 1
    media_lifecycle.cleanup_expired(now=10_000_000)
    assert source_path.read_bytes() == b"existing original"
    assert outside.read_bytes() == b"external"
    # Surviving accepted fixture is excluded from the library even while still on disk.
    assets = media_library_routes.list_assets("video")["assets"]
    assert len(assets) == 1
    assert assets[0]["id"] == survivor
    assert assets[0]["kind"] == "talking_photo"
    assert assets[0]["persistent"] is True
    assert assets[0]["url"] == f"/api/talking-photo/videos/{survivor}"
