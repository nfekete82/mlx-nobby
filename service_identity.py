"""Process-local build identity for MLX nobby services."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess


REVISION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{4,64}$")
PROJECT_DIR = Path(__file__).resolve().parent
STARTED_AT = datetime.now(timezone.utc).isoformat()
PID = os.getpid()


def _normalized_revision(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    return candidate if REVISION_PATTERN.fullmatch(candidate) else None


def _detect_revision() -> str:
    configured = _normalized_revision(os.environ.get("MLX_NOBBY_BUILD_SHA"))
    if configured:
        return configured

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(PROJECT_DIR),
                "rev-parse",
                "--short=12",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"

    return _normalized_revision(result.stdout) or "unknown"


REVISION = _detect_revision()


def service_identity(service: str | None = None) -> dict:
    """Return identity captured when this Python process imported the module."""
    return {
        "service": str(service or "").strip() or None,
        "revision": REVISION,
        "pid": PID,
        "started_at": STARTED_AT,
    }
