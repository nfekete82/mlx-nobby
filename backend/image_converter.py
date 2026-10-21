"""Local bounded image batch conversion with ZIP export."""
import asyncio
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED
import json
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

router = APIRouter()
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_FILES = 40
MAX_PER_FILE = 18 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 45_000_000
# Keep CPU/memory-intensive encodes off the API event loop and serialize them.
_CONVERSION_LIMIT = asyncio.Semaphore(1)

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False


def clean_name(value):
    value = str(value or "image").replace("\\", "/").split("/")[-1]
    return (re.sub(r"[^a-zA-Z0-9äöüÄÖÜß._ -]", "_", value).strip(" .")[:110] or "image")


def convert_bytes(data, name, fmt="WEBP", quality=85, max_edge=0, background="#ffffff"):
    if fmt not in FORMATS or not 40 <= quality <= 100 or not 0 <= max_edge <= 8192:
        raise ValueError("Ungültige Konvertierungsoptionen")
    if Path(name.lower()).suffix not in EXTENSIONS:
        raise ValueError("Nicht unterstütztes Dateiformat")
    if not data or len(data) > MAX_PER_FILE:
        raise ValueError("Datei leer oder zu groß")
    try:
        with Image.open(BytesIO(data)) as im:
            if im.width * im.height > 45_000_000:
                raise ValueError("Maximal 45 Megapixel")
            im = ImageOps.exif_transpose(im)
            im.load()
            if max_edge and max(im.size) > max_edge:
                im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            has_alpha = "A" in im.getbands() or "transparency" in im.info
            if fmt == "JPEG":
                if has_alpha:
                    layer = im.convert("RGBA")
                    base = Image.new("RGBA", im.size, background)
                    base.alpha_composite(layer)
                    im = base.convert("RGB")
                else:
                    im = im.convert("RGB")
            else:
                im = im.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            if fmt == "PNG":
                im.save(output, "PNG", optimize=True, compress_level=9)
            elif fmt == "JPEG":
                im.save(output, "JPEG", quality=quality, optimize=True, progressive=True)
            else:
                im.save(output, "WEBP", quality=quality, method=5)
            return output.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Kein lesbares Bild") from exc


@router.get("/api/image-converter/formats")
def formats():
    return {"inputs": sorted(EXTENSIONS if HEIC_AVAILABLE else EXTENSIONS - {".heic", ".heif"}),
            "outputs": sorted(FORMATS), "heic_available": HEIC_AVAILABLE,
            "max_files": MAX_FILES, "max_file_mb": 18}


@router.post("/api/image-converter/batch")
async def batch(files: list[UploadFile] = File(...), fmt: str = Form("WEBP"),
                quality: int = Form(85), max_edge: int = Form(0),
                background: str = Form("#ffffff")):
    fmt = fmt.upper()
    if fmt not in FORMATS or not 40 <= quality <= 100 or not 0 <= max_edge <= 8192:
        raise HTTPException(422, "Ungültiges Zielformat, Qualität oder Bildgröße")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise HTTPException(422, "Ungültige Hintergrundfarbe")
    if not files or len(files) > MAX_FILES:
        raise HTTPException(413, "Maximal 40 Bilder pro Stapel")
    total = 0
    results = []
    used = set()
    out = BytesIO()
    with ZipFile(out, "w", ZIP_STORED) as archive:
        for file in files:
            name = clean_name(file.filename)
            raw = await file.read(MAX_PER_FILE + 1)
            total += len(raw)
            if len(raw) > MAX_PER_FILE or total > MAX_TOTAL:
                raise HTTPException(413, "Upload überschreitet Größenlimit")
            try:
                async with _CONVERSION_LIMIT:
                    processed = await run_in_threadpool(
                        convert_bytes, raw, name, fmt, quality, max_edge, background
                    )
                stem = clean_name(Path(name).stem)
                target = stem + FORMATS[fmt]
                n = 2
                while target.lower() in used:
                    target = stem + "-" + str(n) + FORMATS[fmt]
                    n += 1
                used.add(target.lower())
                archive.writestr(target, processed)
                results.append({"input": name, "output": target, "before": len(raw),
                                "after": len(processed), "status": "ok"})
            except ValueError as exc:
                results.append({"input": name, "status": "error", "error": str(exc)})
            finally:
                await file.close()
        archive.writestr("conversion-report.json", json.dumps(results, ensure_ascii=False, indent=2))
    if not any(r["status"] == "ok" for r in results):
        raise HTTPException(422, "Keine lesbaren Bilder gefunden")
    return Response(out.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="mlx-nobby-converted.zip"',
                             "Cache-Control": "no-store",
                             "X-Converted-Count": str(sum(r["status"] == "ok" for r in results))})
