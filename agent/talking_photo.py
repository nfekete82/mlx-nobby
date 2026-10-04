"""Local talking-photo orchestration using Nobby TTS and a MuseTalk-compatible server."""

from __future__ import annotations

import base64
import hashlib
import binascii
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from fastapi import HTTPException

from agent import talking_photo_motion


ROOT = Path.home() / ".config/mlx-web/talking-photo"
JOBS = ROOT / "jobs"
OUTPUT = ROOT / "videos"
SPEECH_SERVICE_URL = os.environ.get(
    "SPEECH_SERVICE_URL", "http://127.0.0.1:8050",
).rstrip("/")
MUSETALK_URL = os.environ.get(
    "MUSETALK_URL", "http://127.0.0.1:8070",
).rstrip("/")
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
DATA_URL_PATTERN = re.compile(
    r"^data:image/(?P<kind>png|jpeg);base64,(?P<data>[A-Za-z0-9+/=]+)$",
    re.IGNORECASE,
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ACTIVE_STATUSES = {"queued", "tts", "motion", "lipsync"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

_jobs_lock = threading.RLock()
_render_lock = threading.Lock()


class TalkingPhotoCancelled(RuntimeError):
    pass


def _job_id(value: str) -> str:
    value = str(value or "")
    if not JOB_ID_PATTERN.fullmatch(value):
        raise HTTPException(422, "Ungültige Talking-Photo-Job-ID")
    return value


def _job_file(job_id: str) -> Path:
    return JOBS / f"{_job_id(job_id)}.json"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_job(job_id: str) -> dict:
    path = _job_file(job_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(404, "Talking-Photo-Job nicht gefunden") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(500, "Talking-Photo-Job konnte nicht gelesen werden") from exc
    if not isinstance(value, dict) or value.get("id") != job_id:
        raise HTTPException(500, "Talking-Photo-Job ist beschädigt")
    return value


def _write_job(job: dict) -> None:
    _atomic_json(_job_file(job["id"]), job)


def _update_job(job_id: str, **changes) -> dict:
    with _jobs_lock:
        job = _read_job(job_id)
        if job.get("status") in TERMINAL_STATUSES:
            return job
        job.update(changes)
        _write_job(job)
        return job


def recover_jobs() -> None:
    """Mark durable in-flight jobs as failed after an Agent restart."""
    JOBS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with _jobs_lock:
        for path in JOBS.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(job, dict) or job.get("status") not in ACTIVE_STATUSES:
                continue
            job.update(
                status="failed",
                phase="failed",
                error="Agent wurde während des Talking-Photo-Jobs neu gestartet",
                finished_at=time.time(),
            )
            _atomic_json(path, job)


def decode_image_data_url(value: str) -> tuple[bytes, str]:
    if not isinstance(value, str):
        raise HTTPException(422, "Bild fehlt")
    match = DATA_URL_PATTERN.fullmatch(value.strip())
    if not match:
        raise HTTPException(422, "Unterstützt werden PNG und JPEG")
    try:
        image = base64.b64decode(match.group("data"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "Bilddaten sind ungültig") from exc
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Bild darf maximal 10 MB groß sein")

    kind = match.group("kind").lower()
    valid = (
        kind == "png" and image.startswith(b"\x89PNG\r\n\x1a\n")
        or kind == "jpeg" and image.startswith(b"\xff\xd8\xff")
    )
    if not valid:
        raise HTTPException(422, "Bildformat stimmt nicht mit den Bilddaten überein")
    return image, {"png": ".png", "jpeg": ".jpg"}[kind]


def provider_health(timeout: float = 3.0) -> dict:
    request = urllib.request.Request(
        MUSETALK_URL + "/health",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ready = bool(payload.get("ok")) if isinstance(payload, dict) else False
        return {
            "ready": ready,
            "provider": "musetalk-mac",
            "url": MUSETALK_URL,
            "device": payload.get("device") if isinstance(payload, dict) else None,
            "cached_avatars": (
                payload.get("cached_avatars") if isinstance(payload, dict) else None
            ),
            "setup_command": "./scripts/setup-musetalk-mac",
            "detail": None if ready else "MuseTalk meldet sich nicht bereit",
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {
            "ready": False,
            "provider": "musetalk-mac",
            "url": MUSETALK_URL,
            "device": None,
            "cached_avatars": None,
            "setup_command": "./scripts/setup-musetalk-mac",
            "detail": f"MuseTalk nicht erreichbar: {exc}",
        }


def _request_tts(payload: dict) -> bytes:
    request = urllib.request.Request(
        SPEECH_SERVICE_URL + "/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/mpeg, audio/wav, application/octet-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Speech-Service {exc.code}: {detail[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Speech-Service nicht erreichbar") from exc
    if not audio:
        raise RuntimeError("Speech-Service lieferte kein Audio")
    return audio


def _audio_to_wav(audio: bytes, directory: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg wurde nicht gefunden")
    source = directory / "speech-input.bin"
    target = directory / "speech-16k.wav"
    source.write_bytes(audio)
    process = subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-i", str(source),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode != 0 or not target.is_file():
        raise RuntimeError(
            "TTS-Audio konnte nicht für MuseTalk vorbereitet werden: "
            + (process.stderr or "")[-1000:]
        )
    wav = target.read_bytes()
    if len(wav) < 44 or not wav.startswith(b"RIFF"):
        raise RuntimeError("Ungültiges WAV nach TTS-Konvertierung")
    return wav


def _musetalk_lipsync(image: bytes, audio_wav: bytes, avatar_key: str) -> tuple[bytes, str | None]:
    payload = {
        "avatar_key": avatar_key,
        "video_b64": base64.b64encode(image).decode("ascii"),
        "audio_b64": base64.b64encode(audio_wav).decode("ascii"),
    }
    request = urllib.request.Request(
        MUSETALK_URL + "/lipsync_stream",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/octet-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            video = response.read()
            timing = response.headers.get("X-Timing")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("detail") or detail)
        except ValueError:
            pass
        raise RuntimeError(f"MuseTalk {exc.code}: {detail[:1500]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("MuseTalk nicht erreichbar") from exc
    if len(video) < 32 or b"ftyp" not in video[:32]:
        raise RuntimeError("MuseTalk lieferte kein gültiges MP4")
    return video, timing


def _cancelled(job_id: str) -> bool:
    return bool(_read_job(job_id).get("cancel_requested"))


def _run_job(job_id: str, image: bytes, request_payload: dict) -> None:
    work = ROOT / "work" / job_id
    output = OUTPUT / f"{job_id}.mp4"
    work.mkdir(parents=True, exist_ok=True)
    try:
        with _render_lock:
            if _cancelled(job_id):
                raise TalkingPhotoCancelled()
            _update_job(
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
            audio = _request_tts(tts_payload)

            if _cancelled(job_id):
                raise TalkingPhotoCancelled()
            wav = _audio_to_wav(audio, work)

            media = image
            motion = str(request_payload.get("motion") or "none")
            if motion == "natural":
                if _cancelled(job_id):
                    raise TalkingPhotoCancelled()
                _update_job(job_id, status="motion", phase="motion", progress=0.2)
                try:
                    media = talking_photo_motion.generate_natural_motion(
                        job_id,
                        image,
                        wav,
                        cancelled=lambda: _cancelled(job_id),
                        update=lambda **changes: _update_job(job_id, **changes),
                    )
                except talking_photo_motion.MotionCancelled as exc:
                    raise TalkingPhotoCancelled() from exc

            if _cancelled(job_id):
                raise TalkingPhotoCancelled()
            _update_job(job_id, status="lipsync", phase="lipsync", progress=0.8)
            avatar_key = hashlib.sha256(media).hexdigest()[:24]
            video, timing = _musetalk_lipsync(media, wav, avatar_key)

            if _cancelled(job_id):
                raise TalkingPhotoCancelled()
            OUTPUT.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".mp4.tmp")
            temporary.write_bytes(video)
            os.replace(temporary, output)
            _update_job(
                job_id,
                status="completed",
                phase="completed",
                progress=1.0,
                result={
                    "id": job_id,
                    "mime_type": "video/mp4",
                    "size_bytes": len(video),
                    "provider": "musetalk-mac",
                    "motion": motion,
                    "motion_provider": "ltx-2.5" if motion == "natural" else None,
                    "timing": timing,
                    "video_url": f"/api/talking-photo/videos/{job_id}",
                },
                finished_at=time.time(),
                error=None,
            )
    except TalkingPhotoCancelled:
        output.unlink(missing_ok=True)
        _update_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            result=None,
            error=None,
            finished_at=time.time(),
        )
    except Exception as exc:
        output.unlink(missing_ok=True)
        _update_job(
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
            "MuseTalk ist nicht bereit. Einmalig ./scripts/setup-musetalk-mac ausführen.",
        )
    image, _extension = decode_image_data_url(payload["image_data_url"])
    job_id = secrets.token_hex(12)
    now = time.time()
    motion = str(payload.get("motion") or "none")
    job = {
        "id": job_id,
        "kind": "talking_photo",
        "status": "queued",
        "phase": "queued",
        "progress": 0.0,
        "voice": payload.get("voice"),
        "language": payload["language"],
        "speed": payload.get("speed", 1.0),
        "motion": motion,
        "text_characters": len(payload["text"]),
        "provider": "musetalk-mac",
        "result": None,
        "error": None,
        "cancel_requested": False,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    with _jobs_lock:
        _write_job(job)
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, image, dict(payload)),
        daemon=True,
        name=f"talking-photo-{job_id}",
    )
    thread.start()
    return job


def get_job(job_id: str) -> dict:
    return _read_job(_job_id(job_id))


def cancel_job(job_id: str) -> dict:
    job_id = _job_id(job_id)
    with _jobs_lock:
        job = _read_job(job_id)
        if job.get("status") not in ACTIVE_STATUSES:
            raise HTTPException(409, "Talking-Photo-Job kann nicht mehr abgebrochen werden")
        job["cancel_requested"] = True
        _write_job(job)
        return job


def video_path(video_id: str) -> Path:
    video_id = _job_id(video_id)
    path = (OUTPUT / f"{video_id}.mp4").resolve()
    root = OUTPUT.resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Talking-Photo-Video nicht gefunden")
    return path
