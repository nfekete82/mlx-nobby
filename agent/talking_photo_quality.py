"""High-quality Talking Photo jobs using LTX-2.5 MLX Audio-to-Video."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import threading
import time

from fastapi import HTTPException

from agent import talking_photo, talking_photo_ltx, talking_photo_motion


def provider_health() -> dict:
    return talking_photo_ltx.provider_health()


def _run_quality_job(job_id: str, image: bytes, image_suffix: str, request_payload: dict) -> None:
    work = talking_photo.ROOT / "work" / job_id
    output = talking_photo.OUTPUT / f"{job_id}.mp4"
    work.mkdir(parents=True, exist_ok=True)
    try:
        with talking_photo._render_lock:
            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            talking_photo._update_job(
                job_id,
                status="tts",
                phase="tts",
                started_at=time.time(),
                error=None,
            )
            tts_payload = {
                "input": request_payload["text"],
                "language": request_payload["language"],
            }
            voice = request_payload.get("voice")
            if voice:
                tts_payload["voice"] = voice
            speed = float(request_payload.get("speed", 1.0))
            if speed != 1.0:
                tts_payload["speed"] = speed
            audio = talking_photo._request_tts(tts_payload)

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            wav = talking_photo._audio_to_wav(audio, work)
            audio_seconds = talking_photo_motion.wav_duration_seconds(wav)
            talking_photo._update_job(
                job_id,
                status="motion",
                phase="quality",
                progress=0.2,
            )
            try:
                video, details = talking_photo_ltx.generate(
                    job_id,
                    image,
                    image_suffix,
                    wav,
                    audio_seconds,
                    work,
                    cancelled=lambda: talking_photo._cancelled(job_id),
                    update=lambda **changes: talking_photo._update_job(job_id, **changes),
                )
            except talking_photo_ltx.QualityCancelled as exc:
                raise talking_photo.TalkingPhotoCancelled() from exc

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            talking_photo.OUTPUT.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".mp4.tmp")
            temporary.write_bytes(video)
            os.replace(temporary, output)
            talking_photo._update_job(
                job_id,
                status="completed",
                phase="completed",
                progress=1.0,
                result={
                    "id": job_id,
                    "mime_type": "video/mp4",
                    "size_bytes": len(video),
                    "provider": "ltx-2.5-mlx-a2v",
                    "engine": "quality",
                    "motion": "audio-conditioned",
                    "motion_provider": "ltx-2.5-mlx-a2v",
                    "timing": details,
                    "video_url": f"/api/talking-photo/videos/{job_id}",
                },
                finished_at=time.time(),
                error=None,
            )
    except talking_photo.TalkingPhotoCancelled:
        output.unlink(missing_ok=True)
        talking_photo._update_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            result=None,
            error=None,
            finished_at=time.time(),
        )
    except Exception as exc:
        output.unlink(missing_ok=True)
        talking_photo._update_job(
            job_id,
            status="failed",
            phase="failed",
            result=None,
            error=str(exc)[-4000:],
            finished_at=time.time(),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def create_job(payload: dict) -> dict:
    health = provider_health()
    if not health["ready"]:
        raise HTTPException(
            503,
            health.get("detail") or "LTX Quality ist nicht bereit. ./scripts/setup-ltx-video-mlx ausführen.",
        )
    image, extension = talking_photo.decode_image_data_url(payload["image_data_url"])
    job_id = secrets.token_hex(12)
    now = time.time()
    job = {
        "id": job_id,
        "kind": "talking_photo",
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "voice": payload.get("voice"),
        "language": payload["language"],
        "speed": payload.get("speed", 1.0),
        "motion": "audio-conditioned",
        "engine": "quality",
        "text_characters": len(payload["text"]),
        "provider": "ltx-2.5-mlx-a2v",
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    with talking_photo._jobs_lock:
        talking_photo._write_job(job)
    thread = threading.Thread(
        target=_run_quality_job,
        args=(job_id, image, extension, dict(payload)),
        daemon=True,
        name=f"talking-photo-quality-{job_id}",
    )
    thread.start()
    return job
