"""Small, local provenance index for Library Media Studio.

No media are copied, moved, or accessed by user-supplied paths. Both ends of
every link must be canonical, existing generated media under Nobby roots.
Links are advisory metadata, never a reason to delete the linked source.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from agent import media_lifecycle, media_library_organize

MAX_LINKS = 10000
TARGET_KINDS = frozenset({"video", "talking_photo"})


def _file() -> Path:
    return media_lifecycle.STATE_DIRECTORY / "workflow-links.json"


def _key(kind: str, asset_id: str) -> str:
    return media_lifecycle._key(kind, asset_id)


def _visible(kind: str, asset_id: str) -> bool:
    try:
        return media_library_organize._visible_asset(kind, asset_id) is not None
    except (ValueError, OSError):
        return False


def _read_locked() -> dict:
    try:
        payload = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return {}
    value = payload.get("links")
    if not isinstance(value, dict):
        return {}
    return dict(list(value.items())[:MAX_LINKS])


def _write_locked(links: dict) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".workflow-links.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "links": links}, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parse_key(key: str) -> tuple[str, str] | None:
    if not isinstance(key, str) or ":" not in key:
        return None
    kind, asset_id = key.split(":", 1)
    try:
        _key(kind, asset_id)
    except ValueError:
        return None
    return (kind, asset_id)


def link(source_kind: str, source_id: str, output_kind: str, output_id: str) -> dict:
    """Idempotently link an image to an existing finished video.

    Never accepts arbitrary file paths, external media or acceptance fixtures.
    """
    if source_kind != "image" or output_kind not in TARGET_KINDS:
        raise ValueError("Unsupported source or output media kind")
    source_key = _key(source_kind, source_id)
    output_key = _key(output_kind, output_id)
    with media_lifecycle._lock:
        if not _visible(source_kind, source_id) or not _visible(output_kind, output_id):
            raise FileNotFoundError("Source image or completed output not found")
        links = _read_locked()
        existing = links.get(output_key)
        if existing and existing != source_key:
            raise ValueError("This output is already linked to another source")
        if output_key not in links and len(links) >= MAX_LINKS:
            raise ValueError("Workflow history is full")
        if not existing:
            links[output_key] = source_key
            _write_locked(links)
        return {"source": source_key, "output": output_key, "linked": True}


def snapshot() -> dict:
    """Return only links for valid, still-existing user media."""
    with media_lifecycle._lock:
        entries = _read_locked()
        records = media_lifecycle._load_locked().get("assets", {})
        links = {}
        for output, source in entries.items():
            output_pair = _parse_key(output)
            source_pair = _parse_key(source)
            if not output_pair or not source_pair:
                continue
            if output_pair[0] not in TARGET_KINDS or source_pair[0] != "image":
                continue
            if (_visible_with_records(*output_pair, records) and
                    _visible_with_records(*source_pair, records)):
                links[output] = source
        return {"version": 1, "links": links}


def _visible_with_records(kind: str, asset_id: str, records: dict) -> bool:
    try:
        return media_library_organize._visible_asset(kind, asset_id, records) is not None
    except (ValueError, OSError):
        return False


def forget(kind: str, asset_id: str) -> None:
    """Remove dead edges when a media file is explicitly deleted."""
    target = _key(kind, asset_id)
    with media_lifecycle._lock:
        links = _read_locked()
        cleaned = {child: parent for child, parent in links.items()
                   if child != target and parent != target}
        if len(cleaned) != len(links):
            _write_locked(cleaned)
