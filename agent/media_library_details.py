"""Bounded, local-only metadata lookup for canonical generated media.

Read existing job records; never expose source paths, raw job payloads, or
unverified files. Missing historical metadata stays missing rather than guessed.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

from agent import media_lifecycle


MAX_JOB_FILE_BYTES = 262144
MAX_QUEUE_BYTES = 4_000_000
MAX_JOB_FILES = 2000


def _read_json(path: Path, max_bytes: int = MAX_JOB_FILE_BYTES) -> dict:
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        if not 0 < path.stat().st_size <= max_bytes:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError, TypeError):
        return {}


def _text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    result = "".join(c for c in value.strip() if c.isprintable())
    return result[:max_length] or None


def _positive_int(value: object, maximum: int = 16384) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if 0 < number <= maximum else None


def _safe_fields(result: dict, payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    info = {}
    for name, maximum in (("prompt", 2000), ("model", 128), ("provider", 128),
                          ("operation", 64), ("original_prompt", 2000)):
        value = _text(result.get(name), maximum) or _text(payload.get(name), maximum)
        if value:
            info[name] = value
    for name in ("width", "height", "steps"):
        value = _positive_int(result.get(name), 16384 if name != "steps" else 500)
        if value is not None:
            info[name] = value
    seed = _positive_int(result.get("seed"), 2**32 - 1)
    if seed is not None:
        info["seed"] = seed
    return info


def _index_for(assets: list[dict]) -> dict[str, dict]:
    wanted = {asset["kind"] + ":" + asset["id"] for asset in assets}
    found: dict[str, dict] = {}

    def collect(kind: str, job: dict) -> None:
        if not isinstance(job, dict) or job.get("status") != "completed":
            return
        result = job.get("result")
        if not isinstance(result, dict):
            return
        asset_id = result.get("id")
        if not isinstance(asset_id, str):
            return
        try:
            key = media_lifecycle._key(kind, asset_id)
        except ValueError:
            return
        if key not in wanted:
            return
        payload = job.get("payload")
        if not isinstance(payload, dict):
            request = job.get("request")
            payload = request.get("payload", {}) if isinstance(request, dict) else {}
        candidate = _safe_fields(result, payload)
        if candidate:
            found[key] = {**found.get(key, {}), **candidate}

    # Durable native video history (the public job ID differs from the MP4 ID).
    video_root = media_lifecycle.ROOT / "video-jobs"
    if video_root.is_dir() and not video_root.is_symlink():
        for path in itertools.islice(video_root.glob("*.json"), MAX_JOB_FILES):
            if media_lifecycle.HEX_ID_PATTERN.fullmatch(path.stem):
                collect("video", _read_json(path))

    # Bounded Agent queue covers image jobs, including edits and upscales.
    queue_path = media_lifecycle.ROOT / "media-queue" / "jobs.json"
    queue = _read_json(queue_path, MAX_QUEUE_BYTES)
    for job in itertools.islice(queue.values(), MAX_JOB_FILES):
        if isinstance(job, dict) and job.get("kind") in {"image", "video"}:
            collect(job["kind"], job)

    # Native image reproduction snapshots supplement pruned Agent queue jobs.
    variants = media_lifecycle.IMAGE_ROOT / ".variants"
    if variants.is_dir() and not variants.is_symlink():
        for path in itertools.islice(variants.glob("job-*.json"), MAX_JOB_FILES):
            if media_lifecycle.HEX_ID_PATTERN.fullmatch(path.stem[4:]):
                data = _read_json(path)
                collect("image", data.get("job", {}))

    return found


def enrich(assets: list[dict]) -> list[dict]:
    """Add only reliably recorded, safe metadata; preserve legacy list shape."""
    indexed = _index_for(assets)
    return [{**asset, **indexed.get(asset["kind"] + ":" + asset["id"], {})}
            for asset in assets]
