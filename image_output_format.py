"""Finalize generated PNG artifacts as smaller WebP files.

Providers, edit masks and temporary work files remain PNG. The final WebP
replaces only the successfully encoded artifact, never the input/source.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets

from PIL import Image

WEBP_QUALITY = 90


def finalize_image(path: str | Path) -> Path:
    source = Path(path)
    if source.suffix.lower() != ".png":
        return source
    if os.environ.get("MLX_IMAGE_OUTPUT_FORMAT", "webp").lower() == "png":
        return source
    target = source.with_suffix(".webp")
    temporary = source.with_name(f".{source.stem}-{secrets.token_hex(5)}.webp")
    try:
        with Image.open(source) as image:
            if image.format != "PNG":
                # Keep the original when a provider returns a non-PNG file.
                return source
            image.load()
            # Preserve alpha on generated images and avoid palette conversion errors.
            mode = "RGBA" if ("A" in image.getbands() or "transparency" in image.info) else "RGB"
            output = image.convert(mode)
            output.save(temporary, "WEBP", quality=WEBP_QUALITY, method=5, exact=True)
        with Image.open(temporary) as check:
            if check.format != "WEBP":
                raise OSError("WebP encoder returned unexpected format")
            check.verify()
        # Both files reside in the same managed directory. Publish the finished
        # WebP atomically, then discard the native PNG, keeping failure fallback.
        os.replace(temporary, target)
        source.unlink(missing_ok=True)
        return target
    except (OSError, ValueError, RuntimeError) as error:
        # Keep successful generations available if the optional encoder fails.
        print(f"[image-output] WebP encode failed, keeping PNG: {error}", flush=True)
        return source
    finally:
        temporary.unlink(missing_ok=True)
