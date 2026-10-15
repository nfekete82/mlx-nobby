"""Conservative video-frame conditioning for Talking Photo Longform.

The last *content* frame (not LTX's padded tail) conditions the next chunk.
This reuses ffmpeg on the CPU and does not allocate another MLX model.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from agent.talking_photo_ltx import QualityCancelled


PNG_HEADER = bytes((137, 80, 78, 71, 13, 10, 26, 10))
MAX_REFERENCE_FRAME = 20 * 24


def enabled() -> bool:
    """On by default; one environment switch restores the old independent clips."""
    return os.environ.get("LTX_TALKING_PHOTO_LONGFORM_CONTINUITY", "1").strip().lower() not in {
        "0", "false", "off", "no",
    }


def extract_tail_frame(
    video: Path,
    content_frames: int,
    destination: Path,
    *,
    cancelled,
) -> bytes:
    """Return the last *un-padded* 24-fps frame as PNG reference for the next render.

    ffmpeg's decoded frame number is zero-based. Select frame N-1 when a clip
    contributes N frames, regardless of the trailing 8n+1 LTX padding.
    """
    if cancelled():
        raise QualityCancelled()
    if not 1 <= content_frames <= MAX_REFERENCE_FRAME:
        raise ValueError("Invalid Talking Photo continuity frame boundary")
    if not video.is_file():
        raise FileNotFoundError(video)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg unavailable for continuity frame")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    filter_arg = f"select=eq(n\\,{content_frames - 1})"
    command = [
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(video),
        "-an", "-vf", filter_arg, "-fps_mode", "vfr",
        "-frames:v", "1", "-update", "1", str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out extracting Talking Photo continuation frame") from exc
    if cancelled():
        destination.unlink(missing_ok=True)
        raise QualityCancelled()
    if result.returncode or not destination.is_file():
        raise RuntimeError(
            "Failed to extract Talking Photo continuation frame: "
            + (result.stderr or "")[-400:]
        )
    data = destination.read_bytes()
    if len(data) < 100 or not data.startswith(PNG_HEADER):
        destination.unlink(missing_ok=True)
        raise RuntimeError("Invalid PNG extracted from preceding Talking Photo chunk")
    return data
