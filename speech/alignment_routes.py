"""Local word-timestamp alignment route for generated voiceovers."""

import math
import os
from pathlib import Path
import subprocess
import tempfile

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


SHORTS_ROOT = Path.home() / ".config/mlx-web/shorts"
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga"})


class AlignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    text: str = Field(min_length=1, max_length=20000)
    language: str = Field(default="de", min_length=2, max_length=16)


def _validated_source(value):
    path = Path(str(value or "")).expanduser().resolve()
    root = SHORTS_ROOT.expanduser().resolve()
    if not path.is_relative_to(root):
        raise HTTPException(422, "Alignment-Audio liegt außerhalb des Shorts-Verzeichnisses")
    if path.suffix.lower() not in AUDIO_SUFFIXES or not path.is_file():
        raise HTTPException(422, "Ungültige Alignment-Audiodatei")
    return path


def _result_value(result, key, default=None):
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _segment_value(segment, key, default=None):
    if isinstance(segment, dict):
        return segment.get(key, default)
    return getattr(segment, key, default)


def _serialize_result(result, model_name):
    words = []
    for segment in _result_value(result, "segments", []) or []:
        for item in _segment_value(segment, "words", []) or []:
            word = str(_segment_value(item, "word", "") or "").strip()
            try:
                start = float(_segment_value(item, "start"))
                end = float(_segment_value(item, "end"))
            except (TypeError, ValueError):
                continue
            if not word or not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            entry = {
                "word": word,
                "start": max(0.0, start),
                "end": max(0.0, end),
            }
            probability = _segment_value(item, "probability")
            if isinstance(probability, (int, float)) and math.isfinite(float(probability)):
                entry["probability"] = max(0.0, min(1.0, float(probability)))
            words.append(entry)

    text = str(_result_value(result, "text", "") or "").strip()
    language = str(_result_value(result, "language", "") or "").strip()
    return {
        "text": text,
        "language": language,
        "model": model_name,
        "words": words,
    }


def _convert_to_wav(source, ffmpeg):
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        process = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                wav_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if process.returncode != 0:
            raise RuntimeError(
                "Audio-Konvertierung fehlgeschlagen: " + process.stderr.strip()[-1600:]
            )
        return Path(wav_path)
    except Exception:
        Path(wav_path).unlink(missing_ok=True)
        raise


def install_routes(app, *, get_model, ffmpeg, model_name):
    """Register the local JSON alignment route exactly once."""
    route_path = "/v1/audio/align"
    if any(getattr(route, "path", None) == route_path for route in app.routes):
        return app

    @app.post(route_path)
    def align_voiceover(request: AlignmentRequest):
        source = _validated_source(request.source_path)
        wav_path = None
        try:
            wav_path = _convert_to_wav(source, ffmpeg)
            model = get_model()
            result = model.generate(
                str(wav_path),
                language=request.language,
                word_timestamps=True,
                initial_prompt=request.text[:4000],
            )
            payload = _serialize_result(result, model_name)
            if not payload["words"]:
                raise RuntimeError("Whisper hat keine Wort-Zeitstempel geliefert")
            return payload
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(500, "Audio-Konvertierung hat zu lange gedauert") from exc
        except HTTPException:
            raise
        except Exception as exc:
            print(f"[speech] Alignment-Fehler: {exc!r}", flush=True)
            raise HTTPException(500, str(exc)) from exc
        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)

    return app
