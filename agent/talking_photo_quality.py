"""High-quality Talking Photo jobs using LTX-2.5 MLX Audio-to-Video."""

from __future__ import annotations

from array import array
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import wave

from fastapi import HTTPException

from agent import talking_photo, talking_photo_ltx, talking_photo_motion


AUDIO_DEBUG_ROOT = talking_photo.ROOT / "audio-debug"
_AUDIO_SILENCE_DBFS = -45.0
_AUDIO_WINDOW_MS = 10.0
_DEFAULT_CUSTOM_VOICE_PROFILE = {
    "tts_speed": 1.0,
    "tempo": 1.0,
    "leading_silence_ms": 120.0,
}
_CUSTOM_VOICE_PROFILES = {
    "pervin": {
        "tts_speed": 0.80,
        "tempo": 0.80,
        "leading_silence_ms": 120.0,
    },
}


def provider_health() -> dict:
    return talking_photo_ltx.provider_health()


def _custom_voice_profile(voice: str) -> tuple[str, dict]:
    """Return a per-voice timing profile without ever touching the standard voice."""
    key = str(voice or "").strip().casefold()
    profile = dict(_DEFAULT_CUSTOM_VOICE_PROFILE)
    calibrated = _CUSTOM_VOICE_PROFILES.get(key)
    if calibrated:
        profile.update(calibrated)
        return key, profile
    return "neutral", profile


def _dbfs(value: float) -> float | None:
    if value <= 0:
        return None
    return round(20.0 * math.log10(value / 32768.0), 2)


def _read_pcm16_mono(wav_bytes: bytes) -> tuple[int, array]:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            pcm = handle.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise RuntimeError("Talking-Photo-WAV konnte nicht analysiert werden") from exc

    if channels != 1 or sample_width != 2:
        raise RuntimeError(
            f"Unerwartetes Talking-Photo-WAV: {channels} Kanal/Kanäle, {sample_width * 8} Bit"
        )

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return sample_rate, samples


def _first_active_sample(samples: array, sample_rate: int) -> int | None:
    if not samples or sample_rate <= 0:
        return None
    window = max(1, int(sample_rate * (_AUDIO_WINDOW_MS / 1000.0)))
    threshold = 32768.0 * (10.0 ** (_AUDIO_SILENCE_DBFS / 20.0))
    for start in range(0, len(samples), window):
        end = min(len(samples), start + window)
        count = max(1, end - start)
        rms = math.sqrt(
            sum(int(samples[index]) * int(samples[index]) for index in range(start, end))
            / count
        )
        if rms > threshold:
            return start
    return None


def _trim_custom_voice_leading_silence(
    wav_bytes: bytes,
    leading_silence_ms: float,
) -> bytes:
    """Reduce excessive custom-voice startup delay while keeping a natural pre-roll."""
    sample_rate, samples = _read_pcm16_mono(wav_bytes)
    first_active = _first_active_sample(samples, sample_rate)
    if first_active is None:
        return wav_bytes

    keep_samples = max(
        0,
        int(sample_rate * (float(leading_silence_ms) / 1000.0)),
    )
    cut_samples = max(0, first_active - keep_samples)
    if cut_samples <= 0:
        return wav_bytes

    trimmed = samples[cut_samples:]
    pcm = array("h", trimmed)
    if sys.byteorder != "little":
        pcm.byteswap()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _stretch_custom_voice_wav(wav_bytes: bytes, work: Path, tempo: float) -> bytes:
    """Change custom-voice tempo after TTS so the cloned voice timbre stays intact."""
    if not 0.5 <= tempo <= 2.0:
        raise RuntimeError("Custom-Voice-Tempo muss zwischen 0.5 und 2.0 liegen")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg wurde nicht gefunden")

    source = work / "speech-custom-voice-original.wav"
    target = work / "speech-custom-voice-tempo.wav"
    source.write_bytes(wav_bytes)
    process = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-af",
            f"atempo={tempo:g}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode != 0 or not target.is_file():
        raise RuntimeError(
            "Custom-Voice-Audio konnte nicht für LTX verlangsamt werden: "
            + (process.stderr or "")[-1000:]
        )
    stretched = target.read_bytes()
    if len(stretched) < 44 or not stretched.startswith(b"RIFF"):
        raise RuntimeError("Ungültiges WAV nach Custom-Voice-Tempo-Anpassung")
    return stretched


def _analyze_wav(wav_bytes: bytes) -> dict:
    """Measure the exact 16 kHz mono WAV passed to LTX."""
    sample_rate, samples = _read_pcm16_mono(wav_bytes)
    frame_count = len(samples)
    total_samples = len(samples)
    duration = total_samples / sample_rate if sample_rate else 0.0
    if not total_samples:
        return {
            "sample_rate": sample_rate,
            "channels": 1,
            "sample_width_bytes": 2,
            "frames": frame_count,
            "duration_seconds": 0.0,
            "peak_dbfs": None,
            "rms_dbfs": None,
            "active_rms_dbfs": None,
            "leading_silence_ms": 0.0,
            "trailing_silence_ms": 0.0,
            "silence_threshold_dbfs": _AUDIO_SILENCE_DBFS,
        }

    peak = max(abs(int(sample)) for sample in samples)
    rms = math.sqrt(sum(int(sample) * int(sample) for sample in samples) / total_samples)

    window = max(1, int(sample_rate * (_AUDIO_WINDOW_MS / 1000.0)))
    threshold = 32768.0 * (10.0 ** (_AUDIO_SILENCE_DBFS / 20.0))

    def window_rms(start: int, end: int) -> float:
        count = max(1, end - start)
        return math.sqrt(
            sum(int(samples[index]) * int(samples[index]) for index in range(start, end)) / count
        )

    first_active = None
    last_active_end = None
    for start in range(0, total_samples, window):
        end = min(total_samples, start + window)
        if window_rms(start, end) > threshold:
            if first_active is None:
                first_active = start
            last_active_end = end

    if first_active is None or last_active_end is None:
        leading_ms = duration * 1000.0
        trailing_ms = duration * 1000.0
        active_rms = None
    else:
        leading_ms = (first_active / sample_rate) * 1000.0
        trailing_ms = max(0.0, duration - (last_active_end / sample_rate)) * 1000.0
        active_count = max(1, last_active_end - first_active)
        active_rms_value = math.sqrt(
            sum(
                int(samples[index]) * int(samples[index])
                for index in range(first_active, last_active_end)
            )
            / active_count
        )
        active_rms = _dbfs(active_rms_value)

    return {
        "sample_rate": sample_rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "frames": frame_count,
        "duration_seconds": round(duration, 4),
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": _dbfs(rms),
        "active_rms_dbfs": active_rms,
        "leading_silence_ms": round(leading_ms, 1),
        "trailing_silence_ms": round(trailing_ms, 1),
        "silence_threshold_dbfs": _AUDIO_SILENCE_DBFS,
    }


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
    """Keep the LTX conditioning WAV and metrics outside the disposable work dir."""
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
                "language": request_payload["language"],
            }
            voice = request_payload.get("voice")
            requested_speed = float(request_payload.get("speed", 1.0))
            profile_name = "standard"
            target_leading_silence_ms = None
            tts_speed = requested_speed
            postprocess_tempo = 1.0
            if voice:
                tts_payload["voice"] = voice
                profile_name, profile = _custom_voice_profile(voice)
                target_leading_silence_ms = float(profile["leading_silence_ms"])
                if requested_speed == 1.0:
                    tts_speed = float(profile["tts_speed"])
                    postprocess_tempo = float(profile["tempo"])
            if tts_speed != 1.0:
                tts_payload["speed"] = tts_speed
            audio = talking_photo._request_tts(tts_payload)

            if talking_photo._cancelled(job_id):
                raise talking_photo.TalkingPhotoCancelled()
            wav = talking_photo._audio_to_wav(audio, work)
            if voice and postprocess_tempo != 1.0:
                wav = _stretch_custom_voice_wav(wav, work, postprocess_tempo)
            if voice and target_leading_silence_ms is not None:
                wav = _trim_custom_voice_leading_silence(
                    wav,
                    target_leading_silence_ms,
                )
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
