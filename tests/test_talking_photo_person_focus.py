"""Focused region validation, composition and full-frame preservation."""
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from agent import talking_photo_person_focus as focus


def source_bytes(size=(256, 256)):
    output = io.BytesIO()
    Image.new("RGB", size, "blue").save(output, format="PNG")
    return output.getvalue()


def test_focus_is_normalized_and_bounded():
    raw = source_bytes()
    x, y, w, h = focus.focus_rect(raw, {"x": 1.0, "y": 0.0})
    assert x + w <= 256 and y + h <= 256
    assert w % 2 == h % 2 == 0
    for candidate in ({"x": -0.1, "y": 0.5}, {"x": 0.5, "y": float("nan")}, {}, {"x": True, "y": 0.2}):
        with pytest.raises(ValueError):
            focus.focus_rect(raw, candidate)


def test_crop_and_mask_preserve_full_source_dimensions():
    with tempfile.TemporaryDirectory() as tmp:
        cut, background, mask, rect = focus.prepare(source_bytes(), {"x": .25, "y": .50}, Path(tmp))
        with Image.open(background) as original, Image.open(io.BytesIO(cut)) as cropped:
            assert original.size == (256, 256)
            assert cropped.size == rect[2:]
        with Image.open(mask) as alpha:
            assert alpha.size == rect[2:]
            assert alpha.getpixel((0, 0)) == 0


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_composite_has_original_frame_size_and_audio():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _, bg, mask, rect = focus.prepare(source_bytes(), {"x": .5, "y": .5}, root)
        part = root / "part.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=red:s={rect[2]}x{rect[3]}:r=24:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(part),
        ], check=True, capture_output=True)
        output = focus.composite(part.read_bytes(), bg, mask, rect, root)
        final = root / "final.mp4"
        final.write_bytes(output)
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(final)
        ], check=True, capture_output=True, text=True)
        assert probe.stdout.strip() == "256,256"
        audio = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(final)
        ], check=True, capture_output=True, text=True)
        assert audio.stdout.strip() == "audio"
