"""Safe on-demand thumbnails and metadata for the local media library.

Only canonically named files inside managed output roots can be read.
Previews are low-resolution and cached separately; original MP4s are untouched.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from agent import media_lifecycle


CACHE_ROOT = media_lifecycle.ROOT / "media-library" / "thumbnails"
MAX_PREVIEW_BYTES = 1_500_000


def media_file(kind: str, asset_id: str) -> tuple[Path, os.stat_result]:
    if kind not in {"video", "talking_photo"}:
        raise ValueError("Only video previews are supported")
    root = media_lifecycle._root_for(kind)
    path = root / (media_lifecycle._validate_id(kind, asset_id) + ".mp4")
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    expected = media_lifecycle._expected_path(kind, asset_id)
    if path.resolve() != expected:
        raise ValueError("Media path is not canonical")
    stat = path.stat()
    if not stat.st_size:
        raise FileNotFoundError(path)
    with media_lifecycle._lock:
        record = media_lifecycle._load_locked().get("assets", {}).get(f"{kind}:{asset_id}") or {}
    if isinstance(record, dict) and record.get("owner") == "acceptance":
        raise FileNotFoundError(path)
    return path, stat


def _engine(kind: str, asset_id: str) -> str | None:
    if kind != "talking_photo":
        return None
    path = media_lifecycle.TALKING_PHOTO_JOBS_ROOT / (asset_id + ".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("status") != "completed":
            return None
        engine = (data.get("result") or {}).get("engine") or data.get("engine")
        return engine if engine in {"ltx-distilled", "ltx", "quality", "fast"} else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


@lru_cache(maxsize=1024)
def _probe(path_string: str, mtime_ns: int, size: int) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        process = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "format=duration:stream=width,height,duration",
             "-of", "json", path_string],
            text=True, capture_output=True, timeout=12, check=True,
        )
        data = json.loads(process.stdout)
        stream = (data.get("streams") or [{}])[0]
        duration = stream.get("duration") or (data.get("format") or {}).get("duration")
        seconds = round(float(duration), 2) if duration is not None else None
        if seconds is not None and not (0 < seconds < 86400):
            seconds = None
        return {
            "duration_seconds": seconds,
            "width": int(stream["width"]) if stream.get("width") else None,
            "height": int(stream["height"]) if stream.get("height") else None,
        }
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return {}


def metadata(kind: str, asset_id: str) -> dict:
    path, stat = media_file(kind, asset_id)
    return {
        "kind": kind, "id": asset_id,
        "engine": _engine(kind, asset_id),
        **_probe(str(path), stat.st_mtime_ns, stat.st_size),
    }


def thumbnail(kind: str, asset_id: str) -> Path:
    path, stat = media_file(kind, asset_id)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed")
    signature = hashlib.sha256(
        f"{kind}:{asset_id}:{stat.st_size}:{stat.st_mtime_ns}".encode("ascii")
    ).hexdigest()[:16]
    directory = CACHE_ROOT / kind
    name = f"{asset_id}-{signature}.jpg"
    cached = directory / name
    if cached.is_file() and 100 < cached.stat().st_size <= MAX_PREVIEW_BYTES:
        return cached
    directory.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix=".preview-", suffix=".jpg", dir=directory)
    os.close(fd)
    try:
        process = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(path),
             "-an", "-vf", "scale=640:640:force_original_aspect_ratio=decrease",
             "-frames:v", "1", "-q:v", "5", scratch],
            capture_output=True, text=True, timeout=35,
        )
        if process.returncode or not os.path.isfile(scratch):
            raise RuntimeError("Could not extract video preview")
        size = os.stat(scratch).st_size
        if not 100 < size <= MAX_PREVIEW_BYTES:
            raise RuntimeError("Unexpected thumbnail size")
        os.replace(scratch, cached)
        return cached
    finally:
        Path(scratch).unlink(missing_ok=True)
