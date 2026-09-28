"""Local voice profile management for MLX Nobby.

Voice files are intentionally stored outside Git tracking under speech/voices (or
MLX_TTS_VOICES_DIR). The API never accepts filesystem paths from the client.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from local_security import read_upload
from speech.app import (
    FFMPEG,
    TTS_VOICES_DIR,
    VOICE_MANAGER_CONFIG,
    VOICE_QUALITY_MODES,
    _voice_profile_name,
    clone_generation_options,
    current_default_voice,
    get_voice_profile,
    get_voice_quality,
    list_voice_profiles,
    voice_profile_label,
    voice_profile_metadata,
)


VOICE_UPLOAD_MAX_BYTES = min(
    50 * 1024**2,
    int(os.environ.get("MLX_TTS_VOICE_UPLOAD_MAX_MB", "50")) * 1024**2,
)
VOICE_TRANSCRIPT_MAX_CHARS = 20000
SUPPORTED_AUDIO_SUFFIXES = {
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".opus",
    ".ogg",
    ".oga",
    ".flac",
    ".aac",
    ".webm",
}


class VoiceUpdate(BaseModel):
    name: str | None = None
    transcript: str | None = None
    quality: str | None = None


class DefaultVoiceUpdate(BaseModel):
    voice: str


def _root() -> Path:
    TTS_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    return TTS_VOICES_DIR.resolve()


def _managed_profile_dir(voice: str, *, must_exist: bool = True) -> Path:
    name = _voice_profile_name(voice)
    if not name:
        raise HTTPException(400, "Invalid voice name")
    root = _root()
    candidate = TTS_VOICES_DIR / name
    if candidate.is_symlink():
        raise HTTPException(400, "Symlink voice profiles are not allowed")
    if must_exist and not candidate.is_dir():
        raise HTTPException(404, "Voice profile not found")
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != root:
        raise HTTPException(400, "Voice profile path is outside the managed directory")
    return candidate


def _quality(value: str | None) -> str:
    quality = str(value or "natural").strip().lower()
    if quality not in VOICE_QUALITY_MODES:
        raise HTTPException(400, "Unknown voice quality mode")
    return quality


def _label(value: str) -> str:
    label = " ".join(str(value or "").strip().split())
    if not label or len(label) > 80:
        raise HTTPException(400, "Voice name must contain 1 to 80 characters")
    if not _voice_profile_name(label):
        raise HTTPException(400, "Voice name contains no supported characters")
    return label


def _transcript(value: str) -> str:
    transcript = str(value or "").strip()
    if not transcript:
        raise HTTPException(400, "Transcript must not be empty")
    if len(transcript) > VOICE_TRANSCRIPT_MAX_CHARS:
        raise HTTPException(413, "Transcript is too long")
    return transcript


def _write_json_atomic(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _set_default_voice(label: str):
    _write_json_atomic(VOICE_MANAGER_CONFIG, {"default_voice": label})


def _find_clone(voice: str):
    needle = str(voice or "").strip().casefold()
    for name in list_voice_profiles():
        label = voice_profile_label(name)
        if needle in {name.casefold(), label.casefold()}:
            return name
    return None


def _resolve_voice_label(voice: str) -> str:
    if str(voice or "").strip().casefold() == "serena":
        return "Serena"
    name = _find_clone(voice)
    if name is None:
        raise HTTPException(404, "Voice not found")
    return voice_profile_label(name)


def _reference_stats(path: Path):
    duration = None
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            if rate > 0:
                duration = round(frames / rate, 2)
    except (wave.Error, OSError):
        pass
    return {
        "duration_seconds": duration,
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def _clone_details(name: str):
    profile = get_voice_profile(name)
    if profile is None:
        raise HTTPException(404, "Voice profile not found")
    label = voice_profile_label(name)
    quality = get_voice_quality(name)
    return {
        "id": label,
        "label": label,
        "kind": "clone",
        "quality": quality,
        "sampling": clone_generation_options(name),
        "transcript": profile["ref_text"],
        "is_default": label == current_default_voice(),
        **_reference_stats(profile["reference"]),
    }


def _process_reference(source: Path, target: Path):
    audio_filter = (
        "highpass=f=65,"
        "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-40dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-40dB,"
        "areverse"
    )
    process = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-af",
            audio_filter,
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "FFmpeg failed")
    if not target.is_file() or target.stat().st_size < 1024:
        raise RuntimeError("Processed reference audio is empty")


def install_routes(app):
    methods_by_path = {
        (getattr(route, "path", None), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }

    if ("/v1/audio/voices/manage", "GET") not in methods_by_path:
        @app.get("/v1/audio/voices/manage")
        def list_managed_voices():
            default_voice = current_default_voice()
            clones = [_clone_details(name) for name in list_voice_profiles()]
            return {
                "voices": [
                    {
                        "id": "Serena",
                        "label": "Serena",
                        "kind": "preset",
                        "quality": None,
                        "sampling": None,
                        "transcript": None,
                        "duration_seconds": None,
                        "size_bytes": None,
                        "is_default": default_voice == "Serena",
                    },
                    *clones,
                ],
                "default": default_voice,
                "quality_modes": list(VOICE_QUALITY_MODES),
            }

    if ("/v1/audio/voice-default", "PUT") not in methods_by_path:
        @app.put("/v1/audio/voice-default")
        def set_default_voice(request: DefaultVoiceUpdate):
            label = _resolve_voice_label(request.voice)
            _set_default_voice(label)
            return {"default": label}

    if ("/v1/audio/voices/import", "POST") not in methods_by_path:
        @app.post("/v1/audio/voices/import")
        async def import_voice(
            name: str = Form(...),
            transcript: str = Form(...),
            quality: str = Form("natural"),
            file: UploadFile = File(...),
        ):
            label = _label(name)
            profile_name = _voice_profile_name(label)
            transcript_value = _transcript(transcript)
            quality_value = _quality(quality)
            suffix = Path(file.filename or "reference.wav").suffix.lower()
            if suffix not in SUPPORTED_AUDIO_SUFFIXES:
                raise HTTPException(415, "Unsupported reference audio format")

            final_dir = _managed_profile_dir(profile_name, must_exist=False)
            if final_dir.exists():
                raise HTTPException(409, "Voice profile already exists")

            data = await read_upload(file, VOICE_UPLOAD_MAX_BYTES)
            if not data:
                raise HTTPException(400, "Reference audio is empty")

            temporary_dir = Path(tempfile.mkdtemp(prefix=".voice-import-", dir=_root()))
            try:
                source = temporary_dir / f"source{suffix}"
                reference = temporary_dir / "reference.wav"
                source.write_bytes(data)
                _process_reference(source, reference)
                source.unlink(missing_ok=True)
                (temporary_dir / "transcript.txt").write_text(
                    transcript_value + "\n",
                    encoding="utf-8",
                )
                _write_json_atomic(
                    temporary_dir / "profile.json",
                    {"label": label, "quality": quality_value},
                )
                os.replace(temporary_dir, final_dir)
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(500, "Reference audio processing timed out") from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"Reference audio processing failed: {exc}") from exc
            finally:
                if temporary_dir.exists():
                    shutil.rmtree(temporary_dir, ignore_errors=True)

            return _clone_details(profile_name)

    if ("/v1/audio/voices/{voice}/reference", "GET") not in methods_by_path:
        @app.get("/v1/audio/voices/{voice}/reference")
        def voice_reference(voice: str):
            name = _find_clone(voice)
            if name is None:
                raise HTTPException(404, "Voice profile not found")
            profile_dir = _managed_profile_dir(name)
            reference = profile_dir / "reference.wav"
            if not reference.is_file():
                raise HTTPException(404, "Reference audio not found")
            return FileResponse(
                reference,
                media_type="audio/wav",
                filename=f"{name}-reference.wav",
                headers={"Cache-Control": "no-store"},
            )

    if ("/v1/audio/voices/{voice}", "GET") not in methods_by_path:
        @app.get("/v1/audio/voices/{voice}")
        def voice_details(voice: str):
            if voice.casefold() == "serena":
                return {
                    "id": "Serena",
                    "label": "Serena",
                    "kind": "preset",
                    "quality": None,
                    "sampling": None,
                    "transcript": None,
                    "duration_seconds": None,
                    "size_bytes": None,
                    "is_default": current_default_voice() == "Serena",
                }
            name = _find_clone(voice)
            if name is None:
                raise HTTPException(404, "Voice profile not found")
            return _clone_details(name)

    if ("/v1/audio/voices/{voice}", "PUT") not in methods_by_path:
        @app.put("/v1/audio/voices/{voice}")
        def update_voice(voice: str, request: VoiceUpdate):
            name = _find_clone(voice)
            if name is None:
                raise HTTPException(404, "Voice profile not found")
            profile_dir = _managed_profile_dir(name)
            old_label = voice_profile_label(name)
            was_default = current_default_voice() == old_label
            metadata = voice_profile_metadata(name)
            label = old_label

            if request.transcript is not None:
                (profile_dir / "transcript.txt").write_text(
                    _transcript(request.transcript) + "\n",
                    encoding="utf-8",
                )

            if request.quality is not None:
                metadata["quality"] = _quality(request.quality)

            if request.name is not None:
                label = _label(request.name)
                new_name = _voice_profile_name(label)
                if new_name != name:
                    target = _managed_profile_dir(new_name, must_exist=False)
                    if target.exists():
                        raise HTTPException(409, "Voice profile already exists")
                    os.replace(profile_dir, target)
                    profile_dir = target
                    name = new_name

            metadata["label"] = label
            metadata.setdefault("quality", get_voice_quality(name))
            _write_json_atomic(profile_dir / "profile.json", metadata)

            if was_default and label != old_label:
                _set_default_voice(label)

            return _clone_details(name)

    if ("/v1/audio/voices/{voice}", "DELETE") not in methods_by_path:
        @app.delete("/v1/audio/voices/{voice}")
        def delete_voice(voice: str):
            name = _find_clone(voice)
            if name is None:
                raise HTTPException(404, "Voice profile not found")
            profile_dir = _managed_profile_dir(name)
            label = voice_profile_label(name)
            if current_default_voice() == label:
                _set_default_voice("Serena")
            shutil.rmtree(profile_dir)
            return {"deleted": label, "default": current_default_voice()}
