import json
import os
from pathlib import Path

import pytest

from agent import media_lifecycle


def _storage(monkeypatch, tmp_path):
    root = tmp_path / "mlx-web"
    state = root / "media-lifecycle"
    monkeypatch.setattr(media_lifecycle, "ROOT", root)
    monkeypatch.setattr(media_lifecycle, "STATE_DIRECTORY", state)
    monkeypatch.setattr(media_lifecycle, "STATE_FILE", state / "assets.json")
    monkeypatch.setattr(media_lifecycle, "IMAGE_ROOT", root / "images")
    monkeypatch.setattr(media_lifecycle, "VIDEO_ROOT", root / "videos")
    monkeypatch.setattr(
        media_lifecycle,
        "TALKING_PHOTO_ROOT",
        root / "talking-photo" / "videos",
    )
    monkeypatch.setattr(
        media_lifecycle,
        "TALKING_PHOTO_WORK_ROOT",
        root / "talking-photo" / "work",
    )
    monkeypatch.setattr(
        media_lifecycle,
        "TALKING_PHOTO_JOBS_ROOT",
        root / "talking-photo" / "jobs",
    )
    monkeypatch.setattr(media_lifecycle, "BATCH_UPLOAD_ROOT", root / "batch" / "uploads")
    monkeypatch.setenv("MLX_MEDIA_TEMP_TTL_SECONDS", "60")
    for directory in (
        media_lifecycle.IMAGE_ROOT,
        media_lifecycle.VIDEO_ROOT,
        media_lifecycle.TALKING_PHOTO_ROOT,
        media_lifecycle.TALKING_PHOTO_WORK_ROOT,
        media_lifecycle.TALKING_PHOTO_JOBS_ROOT,
        media_lifecycle.BATCH_UPLOAD_ROOT,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return root


def test_temporary_asset_is_deleted_on_discard(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "1234567890-abcdef123456"
    path = media_lifecycle.IMAGE_ROOT / f"{asset_id}.png"
    path.write_bytes(b"png")

    record = media_lifecycle.register("image", asset_id, path)
    assert record["persistent"] is False
    result = media_lifecycle.discard("image", asset_id)

    assert result["deleted"] is True
    assert result["tracked"] is True
    assert not path.exists()
    assert media_lifecycle.status()["tracked"] == 0


def test_untracked_legacy_asset_is_never_deleted_by_browser_discard(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "1234567890-abcdef123456"
    path = media_lifecycle.IMAGE_ROOT / f"{asset_id}.png"
    path.write_bytes(b"legacy")

    result = media_lifecycle.discard("image", asset_id)

    assert result["deleted"] is False
    assert result["tracked"] is False
    assert path.is_file()


def test_explicit_save_can_adopt_legacy_asset(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "1234567890-abcdef123456"
    path = media_lifecycle.IMAGE_ROOT / f"{asset_id}.png"
    path.write_bytes(b"legacy")

    record = media_lifecycle.persist("image", asset_id)

    assert record["persistent"] is True
    assert record["saved_at"] is not None
    assert media_lifecycle.status()["persistent"] == 1


def test_persisted_asset_survives_discard_and_ttl(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "a" * 24
    path = media_lifecycle.VIDEO_ROOT / f"{asset_id}.mp4"
    path.write_bytes(b"video")

    record = media_lifecycle.register("video", asset_id, path)
    saved = media_lifecycle.persist("video", asset_id)
    assert saved["persistent"] is True
    assert saved["expires_at"] is None

    result = media_lifecycle.discard("video", asset_id)
    assert result["persistent"] is True
    assert path.is_file()

    cleanup = media_lifecycle.cleanup_expired(now=record["expires_at"] + 1000)
    assert cleanup["persistent"] == 1
    assert path.is_file()


def test_expired_tracked_asset_is_removed(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "b" * 24
    path = media_lifecycle.VIDEO_ROOT / f"{asset_id}.mp4"
    path.write_bytes(b"video")
    record = media_lifecycle.register("video", asset_id, path)

    result = media_lifecycle.cleanup_expired(now=record["expires_at"] + 1)

    assert result["expired_assets"] == 1
    assert not path.exists()
    assert media_lifecycle.status()["temporary"] == 0


def test_cleanup_drops_missing_persistent_manifest_entries(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "1" * 24
    path = media_lifecycle.VIDEO_ROOT / f"{asset_id}.mp4"
    path.write_bytes(b"saved")
    media_lifecycle.register("video", asset_id, path, persistent=True)
    path.unlink()

    result = media_lifecycle.cleanup_expired(now=10_000_000)

    assert result["missing"] == 1
    assert media_lifecycle.status()["tracked"] == 0


def test_cleanup_does_not_touch_untracked_legacy_chat_media(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    image = media_lifecycle.IMAGE_ROOT / "1234567890-abcdef123456.png"
    video = media_lifecycle.VIDEO_ROOT / ("c" * 24 + ".mp4")
    image.write_bytes(b"old-image")
    video.write_bytes(b"old-video")
    os.utime(image, (1, 1))
    os.utime(video, (1, 1))

    media_lifecycle.cleanup_expired(now=10_000_000)

    assert image.is_file()
    assert video.is_file()


def test_cleanup_removes_stale_unregistered_talking_photo(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    path = media_lifecycle.TALKING_PHOTO_ROOT / ("d" * 24 + ".mp4")
    path.write_bytes(b"old-talking-photo")
    os.utime(path, (1, 1))

    result = media_lifecycle.cleanup_expired(now=10_000_000)

    assert result["legacy_talking_photo"] == 1
    assert not path.exists()


def test_cleanup_preserves_persisted_talking_photo(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "e" * 24
    path = media_lifecycle.TALKING_PHOTO_ROOT / f"{asset_id}.mp4"
    path.write_bytes(b"saved")
    os.utime(path, (1, 1))
    media_lifecycle.register("talking_photo", asset_id, path, persistent=True)

    media_lifecycle.cleanup_expired(now=10_000_000)

    assert path.is_file()


def test_register_rejects_path_outside_managed_root(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "f" * 24
    outside = tmp_path / f"{asset_id}.mp4"
    outside.write_bytes(b"nope")

    with pytest.raises(ValueError):
        media_lifecycle.register("video", asset_id, outside)

    assert outside.is_file()


def test_stale_talking_photo_scratch_is_removed(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    work = media_lifecycle.TALKING_PHOTO_WORK_ROOT / "old-job"
    work.mkdir()
    (work / "speech.wav").write_bytes(b"wav")
    upload = media_lifecycle.BATCH_UPLOAD_ROOT / "talking-photo-old.png"
    upload.write_bytes(b"png")
    os.utime(work, (1, 1))
    os.utime(upload, (1, 1))

    result = media_lifecycle.cleanup_expired(now=10_000_000)

    assert result["scratch"] == 2
    assert not work.exists()
    assert not upload.exists()


def test_stale_terminal_talking_photo_job_metadata_is_removed(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    terminal = media_lifecycle.TALKING_PHOTO_JOBS_ROOT / ("2" * 24 + ".json")
    active = media_lifecycle.TALKING_PHOTO_JOBS_ROOT / ("3" * 24 + ".json")
    terminal.write_text(json.dumps({"id": "2" * 24, "status": "completed"}), encoding="utf-8")
    active.write_text(json.dumps({"id": "3" * 24, "status": "lipsync"}), encoding="utf-8")
    os.utime(terminal, (1, 1))
    os.utime(active, (1, 1))

    result = media_lifecycle.cleanup_expired(now=10_000_000)

    assert result["job_metadata"] == 1
    assert not terminal.exists()
    assert active.exists()


def test_manifest_contains_no_arbitrary_unmanaged_path(monkeypatch, tmp_path):
    _storage(monkeypatch, tmp_path)
    asset_id = "1234567890-abcdef123456"
    path = media_lifecycle.IMAGE_ROOT / f"{asset_id}.png"
    path.write_bytes(b"png")
    media_lifecycle.register("image", asset_id, path)

    state = json.loads(media_lifecycle.STATE_FILE.read_text(encoding="utf-8"))
    record = state["assets"][f"image:{asset_id}"]
    assert Path(record["path"]) == path.resolve()
