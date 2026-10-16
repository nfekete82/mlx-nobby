"""Bounded region inpainting prep and pixel-preserving composition.

Only explicit region-edit requests use this helper. The original stays
immutable; no memory guard or model load threshold is relaxed.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets

from fastapi import HTTPException
from PIL import Image, ImageFilter, ImageChops

REGION_EDGE = 512
MIN_REGION_EDGE = 256


def _aligned_crop_axis(length: int, before: int, after: int, *, max_edge: int) -> tuple[int, int]:
    span = (min(length, max_edge) // 32) * 32
    if span < MIN_REGION_EDGE or after - before > span:
        raise HTTPException(
            422,
            "Markierter Bereich zu groß oder Bild zu klein: "
            "Bitte eine kleinere Auswahl markieren (maximal 512 Pixel pro Achse).",
        )
    midpoint = (before + after) / 2
    start = max(0, min(int(round(midpoint - span / 2)), length - span))
    # The full mask bounding box must be inside this crop.
    start = max(after - span, min(start, before))
    return start, start + span


def region_box(source_size: tuple[int, int], mask: Image.Image) -> tuple[int, int, int, int]:
    """Return a /32-safe crop enclosing all selected nonzero mask pixels."""
    if mask.size != source_size:
        raise HTTPException(422, "Die Maske muss zur Größe des ersten Referenzbilds passen")
    bbox = mask.getbbox()
    if bbox is None:
        raise HTTPException(422, "Maske enthält keinen markierten Bereich")
    x1, x2 = _aligned_crop_axis(source_size[0], bbox[0], bbox[2], max_edge=REGION_EDGE)
    y1, y2 = _aligned_crop_axis(source_size[1], bbox[1], bbox[3], max_edge=REGION_EDGE)
    return x1, y1, x2, y2


def _private_png(image: Image.Image, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / (".edit-source-" + secrets.token_hex(12) + ".png")
    with open(path, "xb", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        image.save(stream, "PNG")
    return path


def prepare_region(source: Path, mask_source: Path, output: Path):
    """Create local temporary 512px-or-smaller source and matching mask crops."""
    source_crop = None
    mask_crop = None
    try:
        with Image.open(source) as original, Image.open(mask_source) as marked:
            # Generated library pictures are unrotated PNGs. Preserve their
            # pixel coordinates exactly as painted in the browser.
            selection = marked.convert("L")
            crop = region_box(original.size, selection)
            source_crop = _private_png(original.convert("RGB").crop(crop), output)
            mask_crop = _private_png(selection.crop(crop), output)
        return source_crop, mask_crop, crop
    except Exception:
        for file in (source_crop, mask_crop):
            if file is not None:
                file.unlink(missing_ok=True)
        raise


def composite_region(source: Path, mask_source: Path, result: Path,
                     crop: tuple[int, int, int, int], output: Path,
                     *, feather_px: int = 0) -> None:
    """Restore full canvas, leaving all unselected pixels *exactly* unchanged.

    The model only sees a crop; even an imperfect model cannot recolor
    unmarked pixels since we composite through the original mask ourselves.
    """
    temp = None
    try:
        with Image.open(source) as orig, Image.open(mask_source) as mask, Image.open(result) as generated:
            canvas = orig.convert("RGB")
            region = canvas.crop(crop)
            edited = generated.convert("RGB")
            if edited.size != region.size:
                edited = edited.resize(region.size, Image.Resampling.LANCZOS)
            selection = mask.convert("L").crop(crop)
            if not isinstance(feather_px, int) or not 0 <= feather_px <= 12:
                raise ValueError("Ungültige Maskenweichheit (0–12 Pixel)")
            if feather_px:
                # Feather inward only: do not alter a single unselected pixel.
                # A blurred mask alone would extend changes outside selection.
                softened = selection.filter(ImageFilter.GaussianBlur(feather_px))
                selection = ImageChops.darker(selection, softened)
            canvas.paste(Image.composite(edited, region, selection), (crop[0], crop[1]))
            temp = _private_png(canvas, output.parent)
        os.replace(temp, output)
        output.chmod(0o600)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
