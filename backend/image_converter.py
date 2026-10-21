"""Local, model-free and metadata-minimal image conversion helpers."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import re

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener


register_heif_opener()

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "HEIF", "HEIC"}
OUTPUT_SUFFIX = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
MAX_PIXELS = 36_000_000
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 50
MAX_OUTPUT_BYTES = 300 * 1024 * 1024


class ConversionError(ValueError):
    """Recoverable, per-file format or resource error."""


def safe_name(filename: str) -> str:
    """Drop directory components and control characters before ZIP output."""
    name = PurePosixPath(str(filename or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip(" .")
    if not name or name in {".", ".."}:
        raise ConversionError("Dateiname fehlt oder ist ungültig.")
    return name[:160]


def check_options(fmt: str, quality: int, max_dimension: int) -> tuple[str, int, int]:
    fmt = str(fmt or "").lower()
    if fmt not in OUTPUT_SUFFIX:
        raise ConversionError("Zielformat nicht unterstützt.")
    if not isinstance(quality, int) or not 30 <= quality <= 100:
        raise ConversionError("Qualität muss zwischen 30 und 100 liegen.")
    if not isinstance(max_dimension, int) or max_dimension != 0 and not 256 <= max_dimension <= 8192:
        raise ConversionError("Maximale Bildkante: 0 oder 256 bis 8192 Pixel.")
    return fmt, quality, max_dimension


def convert_image(
    source: bytes,
    filename: str,
    *,
    fmt: str = "webp",
    quality: int = 85,
    max_dimension: int = 0,
) -> tuple[str, bytes, tuple[int, int]]:
    """Decode one image; preserve orientation/alpha where possible, strip EXIF.

    Output dimensions are never enlarged. JPEG composites alpha onto white;
    PNG uses lossless deflate; WebP/JPEG use the requested lossy quality.
    """
    fmt, quality, max_dimension = check_options(fmt, quality, max_dimension)
    name = safe_name(filename)
    if PurePosixPath(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ConversionError("Nur PNG, JPG, WebP und HEIC/HEIF werden unterstützt.")
    if not source or len(source) > MAX_FILE_BYTES:
        raise ConversionError("Datei ist leer oder größer als 25 MB.")
    try:
        with Image.open(BytesIO(source)) as decoded:
            if (decoded.format or "").upper() not in ALLOWED_FORMATS:
                raise ConversionError("Datei enthält kein unterstütztes Bildformat.")
            if decoded.width * decoded.height > MAX_PIXELS:
                raise ConversionError("Bild hat mehr als 36 Megapixel.")
            if getattr(decoded, "n_frames", 1) > 1:
                raise ConversionError("Animierte Bilder werden noch nicht unterstützt.")
            decoded.load()
            image = ImageOps.exif_transpose(decoded)
            if max_dimension and max(image.size) > max_dimension:
                image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            if fmt == "jpeg":
                if image.mode in {"RGBA", "LA", "P"} and (
                    image.mode != "P" or "transparency" in image.info
                ):
                    alpha = image.convert("RGBA")
                    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
                    background.alpha_composite(alpha)
                    image = background.convert("RGB")
                else:
                    image = image.convert("RGB")
            elif fmt == "webp":
                image = image.convert("RGBA" if (
                    "A" in image.getbands() or "transparency" in image.info
                ) else "RGB")
            elif image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            size = image.size
            output = BytesIO()
            if fmt == "jpeg":
                image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
            elif fmt == "webp":
                image.save(output, format="WEBP", quality=quality, method=6)
            else:
                image.save(output, format="PNG", optimize=True, compress_level=9)
            payload = output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ConversionError("Bild kann nicht sicher gelesen oder konvertiert werden.") from exc
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ConversionError("Konvertiertes Bild ist zu groß.")
    stem = PurePosixPath(name).stem[:105].strip(" .") or "bild"
    return stem + OUTPUT_SUFFIX[fmt], payload, size
