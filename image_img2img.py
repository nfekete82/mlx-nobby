"""Bounded, source-preserving SDXL img2img preprocessing (CPU only)."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

DEFAULT_STRENGTH = 0.45
MAX_EDGE = 1024
MIN_EDGE = 256


def prepare_sdxl_img2img_source(source: Path, destination: Path) -> tuple[int, int]:
    """Normalize EXIF/orientation, RGB and dimensions; never modify the source.

    Limit generated SDXL pixels to roughly a megapixel on Apple Silicon. Reject
    very narrow panoramas instead of stretching them into invalid dimensions.
    Caller manages the temporary destination and removes it even on failures.
    """
    with Image.open(source) as opened:
        if opened.width <= 0 or opened.height <= 0:
            raise ValueError("Ungültige Referenzbild-Abmessungen")
        image = ImageOps.exif_transpose(opened).convert("RGB")

    if max(image.size) / min(image.size) > MAX_EDGE / MIN_EDGE:
        raise ValueError("Juggernaut img2img unterstützt Bildseitenverhältnisse bis 4:1")

    scale = min(MAX_EDGE / max(image.size), 1.0)
    width = max(MIN_EDGE, int(image.width * scale) // 8 * 8)
    height = max(MIN_EDGE, int(image.height * scale) // 8 * 8)
    # Small images are safely expanded to the minimum SDXL canvas.
    width = min(MAX_EDGE, width)
    height = min(MAX_EDGE, height)
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    with open(destination, "xb", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        image.save(stream, format="PNG")
    return width, height
