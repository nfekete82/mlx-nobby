import io
from pathlib import Path
import wave

from agent import talking_photo_motion
from agent import video_api


def _wav(seconds, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def test_ltx_duration_uses_fast_supported_buckets():
    assert talking_photo_motion.ltx_duration(2.0) == 5
    assert talking_photo_motion.ltx_duration(5.5) == 6
    assert talking_photo_motion.ltx_duration(7.0) == 8
    assert talking_photo_motion.ltx_duration(9.0) == 10
    assert talking_photo_motion.ltx_duration(45.0) == 10


def test_generate_natural_motion_uses_existing_i2v_queue(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    videos = tmp_path / "videos"
    uploads.mkdir()
    videos.mkdir()
    monkeypatch.setattr(talking_photo_motion, "UPLOAD_ROOT", uploads)
    monkeypatch.setattr(talking_photo_motion, "VIDEO_OUTPUT_ROOT", videos)
    monkeypatch.setattr(talking_photo_motion, "POLL_INTERVAL", 0)

    final = videos / ("d" * 24 + ".mp4")
    final.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"video" * 20)
    requests = []

    def fake_request(method, path, payload=None, timeout=15):
        requests.append((method, path, payload))
        if method == "POST" and path == "/jobs":
            first_frame = Path(payload["payload"]["first_frame"])
            assert first_frame.is_file()
            assert payload["operation"] == "i2v"
            assert payload["payload"]["quality"] == "fast"
            assert payload["payload"]["duration"] == 6
            assert payload["payload"]["resize_mode"] == "contain"
            assert "subtle realistic idle motion" in payload["payload"]["prompt"]
            return {"id": "e" * 24, "status": "queued"}
        if method == "GET" and path == f"/jobs/{'e' * 24}":
            return {
                "id": "e" * 24,
                "status": "completed",
                "progress": 1.0,
                "result": {"path": str(final)},
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(video_api, "request", fake_request)
    updates = []
    video = talking_photo_motion.generate_natural_motion(
        "f" * 24,
        b"\x89PNG\r\n\x1a\n" + b"portrait",
        _wav(5.5),
        cancelled=lambda: False,
        update=lambda **changes: updates.append(changes),
    )

    assert b"ftyp" in video[:32]
    assert requests[0][0:2] == ("POST", "/jobs")
    assert updates[-1]["progress"] == 0.75
    assert not list(uploads.iterdir())
