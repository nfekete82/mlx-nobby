"""Composite a selected MuseTalk face region into its original full-frame photo.

Only the selected area is rendered; everything outside remains the source image.
This is a fixed-region compositing mode, not multi-face tracking.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFilter


def focus_rect(image: bytes, focus: dict) -> tuple[int, int, int, int]:
    if not isinstance(focus, dict):
        raise ValueError("Invalid person focus")
    x, y = focus.get("x"), focus.get("y")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
        raise ValueError("Person focus must be normalized coordinates")
    with Image.open(io.BytesIO(image)) as img:
        w, h = img.size
    if min(w, h) < 64:
        raise ValueError("Image too small for person focus")
    crop_w = max(64, int(w * .55) // 2 * 2)
    crop_h = max(64, int(h * .55) // 2 * 2)
    crop_w = min(w - w % 2, crop_w)
    crop_h = min(h - h % 2, crop_h)
    left = max(0, min(w - crop_w, round(x * w - crop_w / 2)))
    top = max(0, min(h - crop_h, round(y * h - crop_h / 2)))
    return left, top, crop_w, crop_h


def prepare(image: bytes, focus: dict, directory: Path) -> tuple[bytes, Path, Path, tuple[int,int,int,int]]:
    rect = focus_rect(image, focus)
    left, top, width, height = rect
    directory.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(image)) as source:
        full = source.convert("RGB")
        # ffmpeg/yuv420p output dimensions must be even.
        full = full.crop((0, 0, full.width - full.width % 2, full.height - full.height % 2))
        background = directory / "full-frame.png"
        full.save(background)
        cut = full.crop((left, top, left + width, top + height))
        buffer = io.BytesIO()
        cut.save(buffer, format="PNG")
    mask = Image.new("L", (width, height), 0)
    d = ImageDraw.Draw(mask)
    edge = max(6, min(width, height) // 14)
    d.rectangle((edge, edge, width - edge, height - edge), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=edge // 2))
    mask_path = directory / "blend-mask.png"
    mask.save(mask_path)
    return buffer.getvalue(), background, mask_path, rect


def composite(talking: bytes, background: Path, mask: Path, rect: tuple[int,int,int,int], directory: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg required for full-scene person focus")
    left, top, width, height = rect
    talking_file = directory / "selected-person.mp4"
    talking_file.write_bytes(talking)
    result = directory / "focused-full-scene.mp4"
    filter_graph = (
        f"[1:v]scale={width}:{height},format=rgba[face];"
        f"[2:v]format=gray[mask];"
        f"[face][mask]alphamerge[masked];"
        f"[0:v][masked]overlay={left}:{top}:shortest=1[v]"
    )
    command = [
        ffmpeg, "-nostdin", "-y", "-v", "error",
        "-loop", "1", "-framerate", "24", "-i", str(background),
        "-i", str(talking_file), "-loop", "1", "-i", str(mask),
        "-filter_complex", filter_graph,
        "-map", "[v]", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(result),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Full-scene person composition failed") from exc
    data = result.read_bytes()
    if len(data) < 32 or b"ftyp" not in data[:32]:
        raise RuntimeError("Invalid composed MP4")
    return data
