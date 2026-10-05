"""Lifecycle management for generated, local media assets.

Ad-hoc image/video outputs are temporary by default. A user download promotes
an asset to persistent storage; otherwise browser cleanup or the TTL sweeper may
remove it. Project-owned assets can be registered as persistent immediately.
Only explicitly managed MLX Nobby output roots are ever deleted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from typing import Iterable


ROOT = Path.home() / ".config/mlx-web"
STATE_DIRECTORY = ROOT / "media-lifecycle"
STATE_FILE = STATE_DIRECTORY / "assets.json"
IMAGE_ROOT = ROOT / "images"
VIDEO_ROOT = ROOT / "videos"
TALKING_PHOTO_ROOT = ROOT / "talking-photo" / "videos"
TALKING_PHOTO_WORK_ROOT = ROOT / "talking-photo" / "work"
TALKING_PHOTO_JOBS_ROOT = ROOT / "talking-photo" / "jobs"
BATCH_UPLOAD_ROOT = ROOT / "batch" / "uploads"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 30 * 24 * 60 * 60
KINDS = frozenset({"image", "video", "talking_photo"})
IMAGE_ID_PATTERN = re.compile(r"^\d{10}-[0-9a-f]{12}$")
HEX_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
TALKING_PHOTO_TERMINAL = frozenset({"completed", "failed", "cancelled"})

_lock = threading.RLock()


def configured_ttl_seconds() -> int:
    raw = os.environ.get("MLX_MEDIA_TEMP_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    return min(MAX_TTL_SECONDS, max(MIN_TTL_SECONDS, value))


def _root_for(kind: str) -> Path:
    value = str(kind or "")
    if value == "image":
        return IMAGE_ROOT
    if value == "video":
        return VIDEO_ROOT
    if value == "talking_photo":
        return TALKING_PHOTO_ROOT
    raise ValueError("unsupported media lifecycle kind")


def _validate_id(kind: str, asset_id: str) -> str:
    value = str(asset_id or "")
    pattern = IMAGE_ID_PATTERN if kind == "image" else HEX_ID_PATTERN
    if not pattern.fullmatch(value):
        raise ValueError("invalid media lifecycle asset id")
    return value


def _expected_path(kind: str, asset_id: str) -> Path:
    asset_id = _validate_id(kind, asset_id)
    suffix = ".png" if kind == "image" else ".mp4"
    return (_root_for(kind) / f"{asset_id}{suffix}").expanduser().resolve()


def _validate_path(kind: str, asset_id: str, path: str | Path | None = None) -> Path:
    expected = _expected_path(kind, asset_id)
    if path is None:
        return expected
    candidate = Path(path).expanduser().resolve()
    if candidate != expected:
        raise ValueError("generated media path does not match its managed asset id")
    return candidate


def _key(kind: str, asset_id: str) -> str:
    _root_for(kind)
    return f"{kind}:{_validate_id(kind, asset_id)}"


def _empty_state() -> dict:
    return {"version": 1, "assets": {}}


def _load_locked() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_state()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(value, dict) or not isinstance(value.get("assets"), dict):
        return _empty_state()
    return {"version": 1, "assets": dict(value["assets"])}


def _write_locked(state: dict) -> None:
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".assets.", suffix=".tmp", dir=STATE_DIRECTORY,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STATE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register(
    kind: str,
    asset_id: str,
    path: str | Path | None = None,
    *,
    persistent: bool = False,
    owner: str = "adhoc",
    ttl_seconds: int | None = None,
) -> dict:
    """Register a generated asset without ever downgrading a persistent one."""
    key = _key(kind, asset_id)
    candidate = _validate_path(kind, asset_id, path)
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    now = time.time()
    ttl = configured_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    ttl = min(MAX_TTL_SECONDS, max(MIN_TTL_SECONDS, ttl))
    with _lock:
        state = _load_locked()
        existing = state["assets"].get(key)
        existing = existing if isinstance(existing, dict) else {}
        keep = bool(existing.get("persistent")) or bool(persistent)
        record = {
            "kind": kind,
            "id": _validate_id(kind, asset_id),
            "path": str(candidate),
            "owner": str(owner or existing.get("owner") or "adhoc")[:80],
            "persistent": keep,
            "created_at": float(existing.get("created_at") or now),
            "updated_at": now,
            "expires_at": None if keep else now + ttl,
            "saved_at": (
                float(existing.get("saved_at") or now)
                if keep else None
            ),
        }
        state["assets"][key] = record
        _write_locked(state)
        return dict(record)


def persist(kind: str, asset_id: str) -> dict:
    """Promote an existing or legacy generated asset to persistent storage."""
    key = _key(kind, asset_id)
    path = _expected_path(kind, asset_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    now = time.time()
    with _lock:
        state = _load_locked()
        existing = state["assets"].get(key)
        if not isinstance(existing, dict):
            # Explicit save/download is safe to use as the point at which a
            # pre-lifecycle legacy asset becomes managed.
            existing = register(kind, asset_id, path)
            state = _load_locked()
            existing = state["assets"].get(key) or existing
        record = dict(existing)
        record.update(
            persistent=True,
            updated_at=now,
            expires_at=None,
            saved_at=float(record.get("saved_at") or now),
        )
        state["assets"][key] = record
        _write_locked(state)
        return dict(record)


def forget(kind: str, asset_id: str) -> bool:
    """Forget lifecycle metadata without touching the media file."""
    key = _key(kind, asset_id)
    with _lock:
        state = _load_locked()
        removed = state["assets"].pop(key, None) is not None
        if removed:
            _write_locked(state)
        return removed


def discard(kind: str, asset_id: str, *, force: bool = False) -> dict:
    """Delete a tracked temporary asset; protect legacy and persistent files."""
    key = _key(kind, asset_id)
    path = _expected_path(kind, asset_id)
    with _lock:
        state = _load_locked()
        record = state["assets"].get(key)
        if not isinstance(record, dict) and not force:
            return {
                "deleted": False,
                "persistent": False,
                "tracked": False,
                "kind": kind,
                "id": asset_id,
            }
        if isinstance(record, dict) and record.get("persistent") and not force:
            return {
                "deleted": False,
                "persistent": True,
                "tracked": True,
                "kind": kind,
                "id": asset_id,
            }
        existed = path.is_file()
        path.unlink(missing_ok=True)
        state["assets"].pop(key, None)
        _write_locked(state)
        return {
            "deleted": existed,
            "persistent": False,
            "tracked": isinstance(record, dict),
            "kind": kind,
            "id": asset_id,
        }


def discard_many(items: Iterable[dict]) -> dict:
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            results.append(discard(str(item.get("kind") or ""), str(item.get("id") or "")))
        except (ValueError, OSError):
            continue
    return {
        "processed": len(results),
        "deleted": sum(1 for item in results if item.get("deleted")),
        "protected": sum(1 for item in results if item.get("persistent")),
        "untracked": sum(1 for item in results if item.get("tracked") is False),
        "results": results,
    }


def _remove_stale_talking_photo_outputs(state: dict, now: float, ttl: int) -> int:
    """Clean legacy/unregistered Talking Photo outputs; that root is disposable-only."""
    removed = 0
    TALKING_PHOTO_ROOT.mkdir(parents=True, exist_ok=True)
    persistent_paths = {
        str(Path(record.get("path", "")).expanduser().resolve())
        for record in state["assets"].values()
        if isinstance(record, dict) and record.get("persistent")
    }
    for path in TALKING_PHOTO_ROOT.glob("*.mp4"):
        try:
            if str(path.resolve()) in persistent_paths:
                continue
            if now - path.stat().st_mtime < ttl:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def _remove_stale_work(now: float, ttl: int) -> int:
    removed = 0
    if TALKING_PHOTO_WORK_ROOT.is_dir():
        for path in TALKING_PHOTO_WORK_ROOT.iterdir():
            try:
                if now - path.stat().st_mtime < ttl:
                    continue
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    if BATCH_UPLOAD_ROOT.is_dir():
        for path in BATCH_UPLOAD_ROOT.glob("talking-photo-*"):
            try:
                if now - path.stat().st_mtime < ttl:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    return removed


def _remove_stale_talking_photo_jobs(now: float, ttl: int) -> int:
    """Prune terminal Talking Photo job JSON after its recovery window."""
    removed = 0
    if not TALKING_PHOTO_JOBS_ROOT.is_dir():
        return removed
    for path in TALKING_PHOTO_JOBS_ROOT.glob("*.json"):
        if not HEX_ID_PATTERN.fullmatch(path.stem):
            continue
        try:
            if now - path.stat().st_mtime < ttl:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("status") not in TALKING_PHOTO_TERMINAL:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return removed


def cleanup_expired(*, now: float | None = None) -> dict:
    """Delete expired temporary assets and stale Talking Photo scratch data."""
    current = time.time() if now is None else float(now)
    ttl = configured_ttl_seconds()
    deleted = 0
    missing = 0
    protected = 0
    with _lock:
        state = _load_locked()
        for key, record in list(state["assets"].items()):
            if not isinstance(record, dict):
                state["assets"].pop(key, None)
                continue
            path = Path(str(record.get("path") or "")).expanduser().resolve()
            try:
                expected = _expected_path(str(record.get("kind") or ""), str(record.get("id") or ""))
            except ValueError:
                state["assets"].pop(key, None)
                continue
            if path != expected:
                state["assets"].pop(key, None)
                continue
            if not path.exists():
                state["assets"].pop(key, None)
                missing += 1
                continue
            if record.get("persistent"):
                protected += 1
                continue
            expires_at = float(record.get("expires_at") or (record.get("created_at") or current) + ttl)
            if expires_at > current:
                continue
            try:
                path.unlink(missing_ok=True)
                deleted += 1
                state["assets"].pop(key, None)
            except OSError:
                continue
        legacy = _remove_stale_talking_photo_outputs(state, current, ttl)
        scratch = _remove_stale_work(current, ttl)
        job_metadata = _remove_stale_talking_photo_jobs(current, ttl)
        _write_locked(state)
    return {
        "deleted": deleted + legacy + scratch + job_metadata,
        "expired_assets": deleted,
        "legacy_talking_photo": legacy,
        "scratch": scratch,
        "job_metadata": job_metadata,
        "missing": missing,
        "persistent": protected,
        "ttl_seconds": ttl,
    }


def status() -> dict:
    with _lock:
        state = _load_locked()
        records = [item for item in state["assets"].values() if isinstance(item, dict)]
    return {
        "ok": True,
        "ttl_seconds": configured_ttl_seconds(),
        "tracked": len(records),
        "temporary": sum(1 for item in records if not item.get("persistent")),
        "persistent": sum(1 for item in records if item.get("persistent")),
    }
