"""Local, bounded image conversion jobs. No model loading or remote services."""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import warnings
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

INPUT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp"})
OUTPUT_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "avif": "AVIF"}
MAX_FILES = 100
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BATCH_BYTES = 220 * 1024 * 1024
MAX_PIXELS = 40_000_000
JOB_LIFETIME_SECONDS = 60 * 60
MAX_JOBS = 6

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nobby-convert")
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_owned_dirs: set[Path] = set()


def _safe_name(filename: str) -> str:
    basename = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß._ -]", "_", basename).strip(" .")
    return basename[:120] or "bild"


def _public(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "files": [dict(item) for item in job["results"]],
        "error": job["error"],
        "created_at": job["created_at"],
    }


def _lookup(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Konvertierungsauftrag nicht gefunden oder abgelaufen")
        job["last_access"] = time.monotonic()
        return job


def _cleanup_expired() -> None:
    folders = []
    with _lock:
        current = time.monotonic()
        for job_id, job in list(_jobs.items()):
            if job["status"] in {"complete", "failed", "cancelled"} and current - job["last_access"] > JOB_LIFETIME_SECONDS:
                _jobs.pop(job_id)
                _owned_dirs.discard(job["directory"])
                folders.append(job["directory"])
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


def _cleanup_at_exit() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
    with _lock:
        folders = tuple(_owned_dirs)
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


atexit.register(_cleanup_at_exit)


def _convert_image(source: Path, destination: Path, options: dict) -> dict:
    target = options["target"]
    save_format = OUTPUT_FORMATS[target]
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise ValueError("Bild überschreitet das Pixel-Limit (40 MP)")
            if getattr(opened, "n_frames", 1) != 1:
                raise ValueError("Animierte oder mehrseitige Bilder werden nicht unterstützt")
            opened.load()
            image = ImageOps.exif_transpose(opened)
            exif = image.getexif().tobytes() if not options["strip_metadata"] else None
            icc = image.info.get("icc_profile") if not options["strip_metadata"] else None
            if options["max_dimension"] and max(image.size) > options["max_dimension"]:
                image.thumbnail((options["max_dimension"], options["max_dimension"]), Image.Resampling.LANCZOS)
            width, height = image.size
            transparent = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            if target == "jpg":
                if transparent:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", image.size, options["background"])
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
            elif transparent:
                image = image.convert("RGBA")
            elif image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            params = {}
            if target == "jpg":
                params.update(quality=options["quality"], optimize=True, progressive=True)
            elif target == "png":
                params.update(optimize=True, compress_level=9)
            elif target == "webp":
                params.update(quality=options["quality"], method=4)
            elif target == "avif":
                params.update(quality=options["quality"], speed=6, max_threads=2)
            if exif:
                params["exif"] = exif
            if icc and len(icc) <= 1_000_000:
                params["icc_profile"] = icc
            image.save(destination, format=save_format, **params)
            return {"width": width, "height": height, "bytes_after": destination.stat().st_size}


def _work(job_id: str, files: list[tuple[str, Path]], options: dict) -> None:
    with _lock:
        job = _jobs[job_id]
        if job["cancel"].is_set():
            job["status"] = "cancelled"
            return
        job["status"] = "running"
    produced = []
    used_names = set()
    for number, (filename, path) in enumerate(files):
        with _lock:
            if job["cancel"].is_set():
                job["status"] = "cancelled"
                break
        stem = Path(filename).stem[:100] or "bild"
        output_name = f"{stem}.{options['target']}"
        suffix = 2
        while output_name.casefold() in used_names:
            output_name = f"{stem}-{suffix}.{options['target']}"
            suffix += 1
        used_names.add(output_name.casefold())
        destination = job["directory"] / f"converted-{number:03d}"
        record = {"source": filename, "output": output_name, "bytes_before": path.stat().st_size}
        try:
            details = _convert_image(path, destination, options)
            record.update(details)
            record["saved_percent"] = round(100 * (1 - details["bytes_after"] / max(record["bytes_before"], 1)), 1)
            record["status"] = "complete"
            produced.append((destination, output_name))
        except (OSError, ValueError, SyntaxError, UnidentifiedImageError) as exc:
            destination.unlink(missing_ok=True)
            record.update(status="failed", error=f"Bild konnte nicht verarbeitet werden: {type(exc).__name__}")
        with _lock:
            job["results"].append(record)
            job["processed"] += 1
        path.unlink(missing_ok=True)
    if job["cancel"].is_set():
        with _lock:
            job["status"] = "cancelled"
        return
    if not produced:
        with _lock:
            job["status"] = "failed"
            job["error"] = "Keine der Dateien konnte verarbeitet werden"
        return
    archive = job["directory"] / "bilder-konvertiert.zip"
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for path, name in produced:
                z.write(path, arcname=name)
            manifest = json.dumps({"files": job["results"]}, ensure_ascii=False, indent=2)
            z.writestr("ergebnisse.json", manifest)
        with _lock:
            job["status"] = "complete"
    except OSError:
        archive.unlink(missing_ok=True)
        with _lock:
            job["status"] = "failed"
            job["error"] = "ZIP-Archiv konnte nicht erstellt werden"


def install_routes(app: FastAPI) -> None:
    @app.get("/api/converter/capabilities")
    def capabilities():
        return {"input_extensions": sorted(INPUT_EXTENSIONS), "output_formats": list(OUTPUT_FORMATS),
                "heic": HEIC_AVAILABLE, "max_files": MAX_FILES,
                "max_file_bytes": MAX_FILE_BYTES, "max_batch_bytes": MAX_BATCH_BYTES}

    @app.post("/api/converter/jobs", status_code=202)
    async def start_job(
        files: list[UploadFile] = File(...),
        target: str = Form("webp"),
        quality: int = Form(85),
        max_dimension: int = Form(0),
        background: str = Form("#ffffff"),
        strip_metadata: bool = Form(True),
    ):
        _cleanup_expired()
        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(422, "1 bis 100 Bilddateien auswählen")
        if target not in OUTPUT_FORMATS:
            raise HTTPException(422, "Nicht unterstütztes Ausgabeformat")
        if not 40 <= quality <= 100 or not 0 <= max_dimension <= 8192:
            raise HTTPException(422, "Ungültige Qualität oder Bildgröße")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
            raise HTTPException(422, "Hintergrundfarbe muss #RRGGBB sein")
        with _lock:
            if len(_jobs) >= MAX_JOBS:
                raise HTTPException(429, "Zu viele gespeicherte Aufträge; später erneut versuchen")
        directory = Path(tempfile.mkdtemp(prefix="mlx-nobby-convert-"))
        paths = []
        total_bytes = 0
        try:
            for number, item in enumerate(files):
                filename = _safe_name(item.filename or "")
                if Path(filename).suffix.lower() not in INPUT_EXTENSIONS:
                    raise HTTPException(422, f"Nicht unterstützte Bilddatei: {filename}")
                if Path(filename).suffix.lower() in {".heic", ".heif"} and not HEIC_AVAILABLE:
                    raise HTTPException(503, "HEIC-Unterstützung ist nicht installiert")
                destination = directory / f"source-{number:03d}"
                length = 0
                with destination.open("wb") as out:
                    while chunk := await item.read(1024 * 1024):
                        length += len(chunk)
                        total_bytes += len(chunk)
                        if length > MAX_FILE_BYTES or total_bytes > MAX_BATCH_BYTES:
                            raise HTTPException(413, "Maximal 25 MB pro Datei und 220 MB insgesamt")
                        out.write(chunk)
                await item.close()
                if not length:
                    raise HTTPException(422, f"Leere Datei: {filename}")
                paths.append((filename, destination))
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "directory": directory, "status": "queued",
               "total": len(paths), "processed": 0, "results": [], "error": None,
               "cancel": threading.Event(), "created_at": datetime.now(timezone.utc).isoformat(),
               "last_access": time.monotonic()}
        with _lock:
            _jobs[job_id] = job
            _owned_dirs.add(directory)
        try:
            _executor.submit(_work, job_id, paths, {
                "target": target, "quality": quality, "max_dimension": max_dimension,
                "background": background, "strip_metadata": strip_metadata,
            })
        except RuntimeError:
            with _lock:
                _jobs.pop(job_id, None)
                _owned_dirs.discard(directory)
            shutil.rmtree(directory, ignore_errors=True)
            raise HTTPException(503, "Konverter derzeit nicht verfügbar")
        return _public(job)

    @app.get("/api/converter/jobs/{job_id}")
    def job_status(job_id: str):
        _cleanup_expired()
        job = _lookup(job_id)
        with _lock:
            return _public(job)

    @app.get("/api/converter/jobs/{job_id}/download")
    def job_download(job_id: str):
        job = _lookup(job_id)
        with _lock:
            if job["status"] != "complete":
                raise HTTPException(409, "Auftrag ist noch nicht abgeschlossen")
            path = job["directory"] / "bilder-konvertiert.zip"
        return FileResponse(path, media_type="application/zip",
                            filename="mlx-nobby-bilder.zip",
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/converter/jobs/{job_id}/files/{index}")
    def single_download(job_id: str, index: int):
        job = _lookup(job_id)
        with _lock:
            if job["status"] != "complete" or index < 0 or index >= len(job["results"]):
                raise HTTPException(404, "Datei nicht verfügbar")
            result = job["results"][index]
            if result["status"] != "complete":
                raise HTTPException(404, "Diese Datei konnte nicht konvertiert werden")
            path = job["directory"] / f"converted-{index:03d}"
            filename = result["output"]
        return FileResponse(path, filename=filename,
                            media_type="application/octet-stream",
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/converter/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = _lookup(job_id)
        with _lock:
            if job["status"] in {"queued", "running"}:
                job["cancel"].set()
            return _public(job)


__all__ = ["install_routes", "HEIC_AVAILABLE", "_convert_image"]
