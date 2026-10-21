"""Image batch converter, isolated from AI services and media library."""

from __future__ import annotations

import asyncio
import json
import tempfile
from zipfile import ZipFile, ZIP_STORED

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.image_converter import (
    MAX_FILE_BYTES, MAX_FILES, MAX_OUTPUT_BYTES, MAX_TOTAL_BYTES,
    ConversionError, check_options, convert_image, safe_name,
)

# Bound concurrent decoding: this runs in the web container, not the MLX worker.
_CONVERSION_SLOT = asyncio.Semaphore(1)


def install_routes(app: FastAPI, frontend_dir) -> None:
    @app.get("/converter", include_in_schema=False)
    def converter_page():
        return FileResponse(frontend_dir / "converter.html", media_type="text/html")

    @app.post("/api/converter/images")
    async def convert_images(
        files: list[UploadFile] = File(...),
        format: str = Form("webp"),
        quality: int = Form(85),
        max_dimension: int = Form(0),
    ):
        try:
            fmt, quality, max_dimension = check_options(format, quality, max_dimension)
        except ConversionError as exc:
            raise HTTPException(422, str(exc)) from exc

        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(422, f"Bitte 1 bis {MAX_FILES} Dateien auswählen.")

        async with _CONVERSION_SLOT:
            output = tempfile.TemporaryFile(mode="w+b")
            converted = []
            failures = []
            input_total = 0
            output_total = 0
            output_names = set()
            try:
                with ZipFile(output, mode="w", compression=ZIP_STORED, allowZip64=True) as archive:
                    for upload in files:
                        try:
                            original = safe_name(upload.filename or "")
                            data = await upload.read(MAX_FILE_BYTES + 1)
                            if not data or len(data) > MAX_FILE_BYTES:
                                raise ConversionError("Datei leer oder größer als 25 MB.")
                            input_total += len(data)
                            if input_total > MAX_TOTAL_BYTES:
                                raise HTTPException(413, "Stapel überschreitet 200 MB.")
                            name, payload, dimensions = await run_in_threadpool(
                                convert_image, data, original, fmt=fmt,
                                quality=quality, max_dimension=max_dimension,
                            )
                            output_total += len(payload)
                            if output_total > MAX_OUTPUT_BYTES:
                                raise HTTPException(413, "Ausgabe überschreitet 300 MB.")
                            base = name.rsplit(".", 1)[0]
                            suffix = "." + name.rsplit(".", 1)[1]
                            unique = name
                            number = 2
                            while unique.casefold() in output_names:
                                unique = f"{base}-{number}{suffix}"
                                number += 1
                            output_names.add(unique.casefold())
                            archive.writestr(unique, payload)
                            converted.append({
                                "source": original, "output": unique,
                                "before_bytes": len(data), "after_bytes": len(payload),
                                "width": dimensions[0], "height": dimensions[1],
                            })
                        except ConversionError as exc:
                            failures.append({
                                "source": (upload.filename or "")[:160],
                                "error": str(exc),
                            })
                        finally:
                            await upload.close()
                    report = {
                        "target_format": fmt, "quality": quality,
                        "max_dimension": max_dimension,
                        "converted": converted, "errors": failures,
                    }
                    archive.writestr("konvertierung-bericht.json", json.dumps(
                        report, ensure_ascii=False, indent=2
                    ).encode("utf-8"))
                if not converted:
                    output.close()
                    error_text = failures[0]["error"] if failures else "Keine gültigen Bilder."
                    raise HTTPException(422, "Keine Datei konvertiert: " + error_text)
                output.seek(0)
            except Exception:
                output.close()
                raise

        def stream():
            try:
                while chunk := output.read(1024 * 1024):
                    yield chunk
            finally:
                output.close()

        return StreamingResponse(
            stream(), media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="mlx-nobby-bilder.zip"',
                "Cache-Control": "no-store",
                "X-Converted-Count": str(len(converted)),
                "X-Failed-Count": str(len(failures)),
                "X-Input-Bytes": str(input_total),
                "X-Output-Bytes": str(output_total),
                "X-Content-Type-Options": "nosniff",
            },
        )
