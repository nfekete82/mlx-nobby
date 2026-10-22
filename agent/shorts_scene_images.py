"""Managed, private scene-image library for Shorts drafts and LTX I2V."""
import base64
import binascii
from io import BytesIO
from pathlib import Path
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from agent import shorts_jobs

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
IMAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def image_directory():
    return shorts_jobs.SHORTS_DIRECTORY / "scene-images"


def image_path(image_id):
    """Only opaque image ids may resolve to local managed PNGs."""
    if not isinstance(image_id, str) or not IMAGE_ID_RE.fullmatch(image_id):
        raise ValueError("invalid Shorts scene image id")
    path = image_directory() / (image_id + ".png")
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Shorts scene image missing; upload it again")
    return path


def upload_image(content_base64):
    """Decode a bounded raster upload, normalize to PNG and persist atomically."""
    if not isinstance(content_base64, str) or len(content_base64) > (MAX_BYTES * 4 // 3 + 8):
        raise ValueError("Shorts scene image exceeds 8 MB")
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid scene image encoding") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Shorts scene image exceeds 8 MB")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Only PNG, JPEG and WebP images are supported")
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Image dimensions are too large")
            source.load()
            picture = ImageOps.exif_transpose(source).convert("RGB")
            picture.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
            output = BytesIO()
            picture.save(output, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or damaged image") from exc
    folder = image_directory()
    folder.mkdir(parents=True, exist_ok=True)
    image_id = uuid.uuid4().hex
    final = folder / (image_id + ".png")
    temporary = folder / (image_id + ".tmp")
    try:
        temporary.write_bytes(output.getvalue())
        temporary.replace(final)
    finally:
        temporary.unlink(missing_ok=True)
    return {"id": image_id, "url": f"/api/mlx/shorts/scene-images/{image_id}"}


def list_images(limit=60):
    folder = image_directory()
    if not folder.is_dir():
        return []
    images = sorted(folder.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    return [{"id": item.stem, "url": f"/api/mlx/shorts/scene-images/{item.stem}"}
            for item in images[:limit] if IMAGE_ID_RE.fullmatch(item.stem) and item.stat().st_size > 0]
