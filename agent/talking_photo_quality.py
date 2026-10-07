"""High-quality Talking Photo jobs using LTX-2.5 MLX Audio-to-Video."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time

from fastapi import HTTPException

from agent import talking_photo, talking_photo_ltx, talking_photo_motion
from agent.talking_photo_audio import _analyze_wav


AUDIO_DEBUG_ROOT = talking_photo.ROOT / "audio-debug"


def provider_health() -> dict:
    return talking_photo_ltx.provider_health()


def tts_language(language: str) -> str:
    """Qwen CustomVoice expects language names, not ISO UI codes.

    Keep this translation local to Talking Photo; it changes no audio samples
    or shared Speech-Service behavior. Clone generation ignores this field.
    """
    names = {
        "de": "german", "en": "english", "fr": "french", "es": "spanish",
        "it": "italian", "pt": "portuguese", "ja": "japanese", "ko": "korean",
        "ru": "russian", "zh": "chinese",
    }
    return names.get(str(language).lower().split("-", 1)[0], language)


def _persist_audio_diagnostics(
    job_id: str,
    voice: str | None,
    language: str,
    profile_name: str,
    tts_speed: float,
    postprocess_tempo: float,
    target_leading_silence_ms: float | None,
    wav_bytes: bytes,
    stats: dict,
) -> dict:
    """Keep the source WAV; the renderer separately retains its padded conditioning WAV."""
    AUDIO_DEBUG_ROOT.mkdir(parents=True, exist_ok=True)
    label = str(voice or "default").strip() or "default"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "voice"
    stem = f"{job_id}-{slug[:48]}"
    wav_path = AUDIO_DEBUG_ROOT / f"{stem}.wav"
    json_path = AUDIO_DEBUG_ROOT / f"{stem}.json"
    wav_path.write_bytes(wav_bytes)
    metadata = {
        "job_id": job_id,
        "voice": voice,
        "language": language,
        "profile": profile_name,
        "tts_speed": tts_speed,
        "postprocess_tempo": postprocess_tempo,
        "target_leading_silence_ms": target_leading_silence_ms,
        "wav_path": str(wav_path),
        "stats": stats,
        "stage": "source-before-padding",
    }
    json_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "wav_path": str(wav_path),
        "metadata_path": str(json_path),
        "profile": profile_name,
        "tts_speed": tts_speed,
        "postprocess_tempo": postprocess_tempo,
        "target_leading_silence_ms": target_leading_silence_ms,
        "stats": stats,
    }


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
                "language": tts_language(request_payload["language"]),
            }
            voice = request_payload.get("voice")
            requested_speed = float(request_payload.get("speed", 1.0))
            profile_name = "standard"
            target_leading_silence_ms = None
            tts_speed = requested_speed
            postprocess_tempo = 1.0
            if voice:
                tts_payload["voice"] = voice
                profile_name = "native"
            # Only an explicitly requested speed is forwarded. No voice-specific
            # timing, second atempo pass, silence trimming or duration matching.
            if tts_speed != 1.0:
                tts_payload["speed"] = tts_speed
            audio = talking_photo._request_tts(tts_payload)

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            wav = talking_photo._audio_to_wav(audio, work)
            audio_seconds = talking_photo_motion.wav_duration_seconds(wav)
            audio_stats = _analyze_wav(wav)
            audio_diagnostics = _persist_audio_diagnostics(
                job_id,
                voice,
                request_payload["language"],
                profile_name,
                tts_speed,
                postprocess_tempo,
                target_leading_silence_ms,
                wav,
                audio_stats,
            )
            talking_photo._update_job(
                job_id,
                status="motion",
                phase="quality",
                progress=0.2,
                audio_diagnostics=audio_diagnostics,
            )
            debug_dir = talking_photo_ltx.debug_directory(job_id)
            if debug_dir is not None:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / "tts-output.bin").write_bytes(audio)
                (debug_dir / "request.json").write_text(
                    json.dumps({"tts_request": tts_payload, "voice": voice,
                                "language": request_payload["language"]},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                )
            try:
                video, details = talking_photo_ltx.generate(
                    job_id,
                    image,
                    image_suffix,
                    wav,
                    audio_seconds,
                    work,
                    debug_dir=debug_dir,
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
                    "audio_diagnostics": audio_diagnostics,
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
