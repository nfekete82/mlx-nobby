import base64
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent import talking_photo


def _data_url(kind, payload):
    return f"data:image/{kind};base64," + base64.b64encode(payload).decode("ascii")


def _prepare_storage(monkeypatch, tmp_path):
    root = tmp_path / "talking-photo"
    monkeypatch.setattr(talking_photo, "ROOT", root)
    monkeypatch.setattr(talking_photo, "JOBS", root / "jobs")
    monkeypatch.setattr(talking_photo, "OUTPUT", root / "videos")
    talking_photo.JOBS.mkdir(parents=True)
    talking_photo.OUTPUT.mkdir(parents=True)


def test_decode_image_data_url_accepts_png():
    image = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    decoded, extension = talking_photo.decode_image_data_url(_data_url("png", image))
    assert decoded == image
    assert extension == ".png"


def test_decode_image_data_url_rejects_mismatched_payload():
    with pytest.raises(HTTPException) as error:
        talking_photo.decode_image_data_url(
            _data_url("jpeg", b"\x89PNG\r\n\x1a\n" + b"x" * 20)
        )
    assert error.value.status_code == 422


def test_create_job_requires_ready_musetalk(monkeypatch):
    monkeypatch.setattr(
        talking_photo,
        "provider_health",
        lambda: {
            "ready": False,
            "provider": "musetalk-mac",
            "setup_command": "./scripts/setup-musetalk-mac",
        },
    )
    payload = {
        "image_data_url": _data_url("png", b"\x89PNG\r\n\x1a\n" + b"x" * 20),
        "text": "Hallo",
        "voice": None,
        "language": "de",
        "speed": 1.0,
    }
    with pytest.raises(HTTPException) as error:
        talking_photo.create_job(payload)
    assert error.value.status_code == 503


def test_run_job_uses_selected_voice_and_writes_video(monkeypatch, tmp_path):
    _prepare_storage(monkeypatch, tmp_path)
    job_id = "a" * 24
    job = {
        "id": job_id,
        "kind": "talking_photo",
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "voice": "Lisa Voice",
        "language": "de",
        "speed": 1.0,
        "motion": "none",
        "text_characters": 5,
        "provider": "musetalk-mac",
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": 1.0,
        "started_at": None,
        "finished_at": None,
    }
    talking_photo._write_job(job)

    tts_payloads = []
    lipsync_calls = []

    def fake_tts(payload):
        tts_payloads.append(payload)
        return b"fake-mp3"

    def fake_wav(audio, directory):
        assert audio == b"fake-mp3"
        assert Path(directory).is_dir()
        return b"RIFF" + b"\x00" * 64

    def fake_lipsync(image, audio, avatar_key):
        lipsync_calls.append((image, audio, avatar_key))
        return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64, "total_s=1.25"

    monkeypatch.setattr(talking_photo, "_request_tts", fake_tts)
    monkeypatch.setattr(talking_photo, "_audio_to_wav", fake_wav)
    monkeypatch.setattr(talking_photo, "_musetalk_lipsync", fake_lipsync)

    source_image = b"\x89PNG\r\n\x1a\n" + b"photo"
    talking_photo._run_job(
        job_id,
        source_image,
        {
            "text": "Hallo",
            "voice": "Lisa Voice",
            "language": "de",
            "speed": 1.0,
            "motion": "none",
        },
    )

    finished = talking_photo.get_job(job_id)
    assert finished["status"] == "completed"
    assert finished["phase"] == "completed"
    assert finished["result"]["provider"] == "musetalk-mac"
    assert finished["result"]["motion"] == "none"
    assert finished["result"]["motion_provider"] is None
    assert finished["result"]["video_url"] == f"/api/talking-photo/videos/{job_id}"
    assert (talking_photo.OUTPUT / f"{job_id}.mp4").is_file()

    assert tts_payloads == [{
        "input": "Hallo",
        "language": "de",
        "voice": "Lisa Voice",
    }]
    assert len(lipsync_calls) == 1
    assert lipsync_calls[0][0] == source_image
    assert lipsync_calls[0][1].startswith(b"RIFF")
    assert len(lipsync_calls[0][2]) == 24


def test_run_job_natural_motion_feeds_ltx_video_into_musetalk(monkeypatch, tmp_path):
    _prepare_storage(monkeypatch, tmp_path)
    job_id = "c" * 24
    talking_photo._write_job({
        "id": job_id,
        "kind": "talking_photo",
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "voice": None,
        "language": "de",
        "speed": 1.0,
        "motion": "natural",
        "text_characters": 5,
        "provider": "musetalk-mac",
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": 1.0,
        "started_at": None,
        "finished_at": None,
    })

    source_image = b"\x89PNG\r\n\x1a\n" + b"portrait"
    motion_video = b"\x00\x00\x00\x18ftypisom" + b"motion" * 20
    calls = []

    monkeypatch.setattr(talking_photo, "_request_tts", lambda payload: b"fake-mp3")
    monkeypatch.setattr(
        talking_photo,
        "_audio_to_wav",
        lambda audio, directory: b"RIFF" + b"\x00" * 64,
    )

    def fake_motion(job_id_arg, image, wav, *, cancelled, update):
        assert job_id_arg == job_id
        assert image == source_image
        assert wav.startswith(b"RIFF")
        assert cancelled() is False
        update(progress=0.55)
        calls.append("motion")
        return motion_video

    def fake_lipsync(media, wav, avatar_key):
        assert media == motion_video
        assert wav.startswith(b"RIFF")
        calls.append("lipsync")
        return b"\x00\x00\x00\x18ftypisom" + b"final" * 20, "total_s=2.0"

    monkeypatch.setattr(
        talking_photo.talking_photo_motion,
        "generate_natural_motion",
        fake_motion,
    )
    monkeypatch.setattr(talking_photo, "_musetalk_lipsync", fake_lipsync)

    talking_photo._run_job(
        job_id,
        source_image,
        {
            "text": "Hallo",
            "voice": None,
            "language": "de",
            "speed": 1.0,
            "motion": "natural",
        },
    )

    finished = talking_photo.get_job(job_id)
    assert calls == ["motion", "lipsync"]
    assert finished["status"] == "completed"
    assert finished["result"]["motion"] == "natural"
    assert finished["result"]["motion_provider"] == "ltx-2.5"


def test_recover_jobs_marks_inflight_motion_job_failed(monkeypatch, tmp_path):
    _prepare_storage(monkeypatch, tmp_path)
    job_id = "b" * 24
    talking_photo._write_job({
        "id": job_id,
        "status": "motion",
        "phase": "motion",
        "error": None,
    })

    talking_photo.recover_jobs()

    recovered = json.loads(
        (talking_photo.JOBS / f"{job_id}.json").read_text(encoding="utf-8")
    )
    assert recovered["status"] == "failed"
    assert "neu gestartet" in recovered["error"]
