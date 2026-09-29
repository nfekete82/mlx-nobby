"""Application version endpoint backed by the repository VERSION file."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from fastapi import FastAPI


PROJECT_DIR = Path(__file__).resolve().parents[1]
VERSION_FILE = PROJECT_DIR / "VERSION"


def _read_version() -> str:
    override = str(os.environ.get("MLX_NOBBY_VERSION") or "").strip()
    if override:
        return override

    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""

    return value or "0.0.0"


def _read_commit() -> str | None:
    override = str(os.environ.get("MLX_NOBBY_COMMIT") or "").strip()
    if override:
        return override[:12]

    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_DIR), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    return value or None


def version_info() -> dict:
    return {
        "name": "MLX Nobby",
        "version": _read_version(),
        "commit": _read_commit(),
    }


def install_routes(app: FastAPI) -> None:
    @app.get("/api/version")
    def api_version():
        return version_info()


__all__ = ["install_routes", "version_info"]
