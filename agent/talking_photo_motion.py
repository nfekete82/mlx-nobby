"""Natural portrait motion for Talking Photo using the existing LTX I2V queue."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import time
import wave

from fastapi import HTTPException


UPLOAD_ROOT = Path.home() / ".config/mlx-web/batch/uploads"
VIDEO_OUTPUT_ROOT = Path.home() / ".config/mlx-web/videos"
TERMINAL = {"completed", "failed", "cancelled"}
POLL_INTERVAL = 0.75
NATURAL_MOTION_PROMPT = (
    "The exact same person remains clearly identifiable and stays in the same setting and framing. "
    "Create subtle realistic idle motion for a person about to speak to camera: small natural head turns "
    "and nods, occasional blinking, gentle eye movement, natural breathing, and slight shoulder and upper-body "
    "movement. Keep the head mostly facing the camera. Preserve facial features, hairstyle, clothing, body shape, "
    "background, lighting, and camera position. Keep the mouth relaxed with minimal motion because precise lip sync "
    "will be added afterward. No large gestures, no camera movement, no zoom, no scene change, no morphing, no "
    "identity drift, no extra people, no exaggerated expression."
)


class MotionCancelled(RuntimeError):
    pass


def wav_duration_seconds(audio_wav: bytes) -> float:
    """Return PCM WAV duration without invoking another process."""
    try:
        with wave.open(io.BytesIO(audio_wav), "rb") as handle:
            rate = int(handle.getframerate())
            frames = int(handle.getnframes())
    except (wave.Error, EOFError, OSError) as exc:
        raise RuntimeError("TTS-WAV-Dauer konnte nicht gelesen werden") from exc
    if rate <= 0 or frames <= 0:
        raise RuntimeError("TTS-WAV hat keine gültige Dauer")
    return frames / rate


def ltx_duration(audio_seconds: float) -> int:
    """Pick a useful fast-profile clip length; MuseTalk can cycle it for longer speech."""
    if audio_seconds <= 5:
        return 5
    if audio_seconds <= 6:
        return 6
    if audio_seconds <= 8:
        return 8
    return 10


def _extension(image: bytes) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise RuntimeError("Talking-Photo-Bildformat ist für LTX nicht unterstützt")


def _validated_video_path(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    root = VIDEO_OUTPUT_ROOT.expanduser().resolve()
    if path.parent != root or path.suffix.lower() != ".mp4" or not path.is_file():
        raise RuntimeError("LTX lieferte kein gültiges lokales Video")
    return path


def generate_natural_motion(
    job_id: str,
    image: bytes,
    audio_wav: bytes,
    *,
    cancelled,
    update=None,
) -> bytes:
    """Create a short identity-preserving I2V clip and return its MP4 bytes."""
    from agent import video_api

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = _extension(image)
    source = UPLOAD_ROOT / f"talking-photo-{job_id}{suffix}"
    source.write_bytes(image)
    duration = ltx_duration(wav_duration_seconds(audio_wav))
    seed = int(hashlib.sha256(image).hexdigest()[:8], 16) & 0x7FFFFFFF
    request_payload = {
        "operation": "i2v",
        "payload": {
            "prompt": NATURAL_MOTION_PROMPT,
            "model": "auto",
            "profile": "standard",
            "quality": "fast",
            "duration": duration,
            "fps": 24,
            "seed": seed,
            "first_frame": str(source),
            "resize_mode": "contain",
        },
        "chat_id": f"talking-photo:{job_id}",
        "run_id": job_id,
        "chat_revision": 0,
    }

    child_id = None
    try:
        queued = video_api.request("POST", "/jobs", request_payload, timeout=30)
        child_id = str(queued.get("id") or "")
        if not child_id:
            raise RuntimeError("LTX-Bewegungsjob lieferte keine Job-ID")

        while True:
            if cancelled():
                try:
                    video_api.request("POST", f"/jobs/{child_id}/cancel", {}, timeout=30)
                except HTTPException:
                    pass
                raise MotionCancelled()

            child = video_api.request("GET", f"/jobs/{child_id}", timeout=15)
            status = str(child.get("status") or "")
            if update is not None:
                raw_progress = child.get("progress")
                if isinstance(raw_progress, (int, float)) and not isinstance(raw_progress, bool):
                    progress = max(0.0, min(1.0, float(raw_progress)))
                    update(progress=0.2 + progress * 0.55)

            if status == "completed":
                result = child.get("result") or {}
                path = _validated_video_path(result.get("path"))
                video = path.read_bytes()
                if len(video) < 32 or b"ftyp" not in video[:32]:
                    raise RuntimeError("LTX-Bewegung lieferte kein gültiges MP4")
                return video
            if status == "failed":
                detail = str(child.get("error") or "Unbekannter LTX-Fehler")
                raise RuntimeError(f"LTX-Bewegung fehlgeschlagen: {detail[-3000:]}")
            if status == "cancelled":
                if cancelled():
                    raise MotionCancelled()
                raise RuntimeError("LTX-Bewegungsjob wurde abgebrochen")
            if status in TERMINAL:
                raise RuntimeError(f"Unerwarteter LTX-Bewegungsstatus: {status}")

            time.sleep(POLL_INTERVAL)
    finally:
        source.unlink(missing_ok=True)
