"""Persistent on-device organization metadata for the generated media library.

No original media are moved or duplicated. Every mutation validates canonical
media IDs and ownership; acceptance fixtures remain excluded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from agent import media_lifecycle

COLLECTION_LIMIT = 100
BATCH_LIMIT = 100
ITEM_LIMIT = 5000
NAME_LIMIT = 60
COLLECTION_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _file() -> Path:
    return media_lifecycle.STATE_DIRECTORY / "collections.json"


def _empty() -> dict:
    return {"version": 1, "favorites": [], "collections": []}


def _key(kind: str, asset_id: str) -> str:
    return media_lifecycle._key(kind, asset_id)


def _visible_asset(kind: str, asset_id: str, records: dict | None = None) -> Path | None:
    key = _key(kind, asset_id)
    path = media_lifecycle._expected_path(kind, asset_id)
    if path.is_symlink() or not path.is_file():
        return None
    if path.resolve() != media_lifecycle._expected_path(kind, asset_id):
        return None
    if path.stat().st_size <= 0:
        return None
    if records is None:
        records = media_lifecycle._load_locked().get("assets", {})
    record = records.get(key, {})
    if isinstance(record, dict) and record.get("owner") == "acceptance":
        return None
    return path


def _valid_key(value: str, records: dict | None = None) -> bool:
    if not isinstance(value, str) or ":" not in value:
        return False
    try:
        kind, asset_id = value.split(":", 1)
        _key(kind, asset_id)
        return _visible_asset(kind, asset_id, records) is not None
    except (ValueError, OSError):
        return False


def _read_locked() -> dict:
    try:
        value = json.loads(_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty()
    if not isinstance(value, dict) or value.get("version") != 1:
        return _empty()
    favorites = value.get("favorites", [])
    collections = value.get("collections", [])
    if not isinstance(favorites, list) or not isinstance(collections, list):
        return _empty()
    result = _empty()
    # Load lifecycle ownership once, rather than re-reading JSON per item.
    records = media_lifecycle._load_locked().get("assets", {})
    result["favorites"] = [
        k for k in dict.fromkeys(v for v in favorites[:ITEM_LIMIT] if isinstance(v, str))
        if _valid_key(k, records)
    ]
    ids = set()
    for entry in collections[:COLLECTION_LIMIT]:
        if not isinstance(entry, dict):
            continue
        cid, name, items = entry.get("id"), entry.get("name"), entry.get("items")
        if not isinstance(cid, str) or not COLLECTION_ID_RE.fullmatch(cid) or cid in ids:
            continue
        if not isinstance(name, str) or not name.strip() or len(name) > NAME_LIMIT:
            continue
        if not isinstance(items, list):
            continue
        ids.add(cid)
        result["collections"].append({
            "id": cid, "name": name,
            "items": [
                k for k in dict.fromkeys(v for v in items[:ITEM_LIMIT] if isinstance(v, str))
                if _valid_key(k, records)
            ],
        })
    return result


def _write_locked(value: dict) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".collections.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot() -> dict:
    with media_lifecycle._lock:
        return _read_locked()


def create_collection(name: str) -> dict:
    if not isinstance(name, str) or len(name.strip()) < 1 or len(name.strip()) > NAME_LIMIT:
        raise ValueError("Collection name must be 1–60 characters")
    name = name.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Invalid collection name")
    with media_lifecycle._lock:
        state = _read_locked()
        if len(state["collections"]) >= COLLECTION_LIMIT:
            raise ValueError("Too many collections")
        if any(c["name"].casefold() == name.casefold() for c in state["collections"]):
            raise ValueError("Collection name already exists")
        record = {"id": secrets.token_hex(8), "name": name, "items": []}
        state["collections"].append(record)
        _write_locked(state)
        return record


def delete_collection(collection_id: str) -> dict:
    if not COLLECTION_ID_RE.fullmatch(str(collection_id)):
        raise ValueError("Invalid collection")
    with media_lifecycle._lock:
        state = _read_locked()
        kept = [c for c in state["collections"] if c["id"] != collection_id]
        if len(kept) == len(state["collections"]):
            raise ValueError("Unknown collection")
        state["collections"] = kept
        _write_locked(state)
    return {"deleted": True, "id": collection_id, "media_deleted": False}


def update_many(items: list, operation: str, collection_id: str | None = None) -> dict:
    valid_ops = {"favorite", "unfavorite", "add_collection", "remove_collection"}
    if operation not in valid_ops:
        raise ValueError("Invalid organization action")
    if not isinstance(items, list) or not 1 <= len(items) <= BATCH_LIMIT:
        raise ValueError("Select 1–100 assets")
    keys = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid asset")
        keys.append(_key(item.get("kind"), item.get("id")))
    keys = list(dict.fromkeys(keys))
    with media_lifecycle._lock:
        state = _read_locked()
        target = None
        if operation.endswith("_collection"):
            if not isinstance(collection_id, str) or not COLLECTION_ID_RE.fullmatch(collection_id):
                raise ValueError("Invalid collection ID")
            target = next((c for c in state["collections"] if c["id"] == collection_id), None)
            if target is None:
                raise ValueError("Unknown collection")
        for key in keys:
            kind, asset_id = key.split(":", 1)
            if _visible_asset(kind, asset_id) is None:
                raise ValueError("Asset missing or unavailable")
        # Validate target capacities before promoting any temporary media.
        if operation == "favorite" and len(set(state["favorites"]) | set(keys)) > ITEM_LIMIT:
            raise ValueError("Too many favorites")
        if operation == "add_collection" and len(set(target["items"]) | set(keys)) > ITEM_LIMIT:
            raise ValueError("Collection is full")
        if operation in {"favorite", "add_collection"}:
            for key in keys:
                kind, asset_id = key.split(":", 1)
                media_lifecycle.persist(kind, asset_id)
        if operation in {"favorite", "unfavorite"}:
            existing = set(state["favorites"])
            if operation == "favorite":
                existing.update(keys)
                if len(existing) > ITEM_LIMIT:
                    raise ValueError("Too many favorites")
            else:
                existing.difference_update(keys)
            state["favorites"] = sorted(existing)
        else:
            existing = set(target["items"])
            if operation == "add_collection":
                existing.update(keys)
                if len(existing) > ITEM_LIMIT:
                    raise ValueError("Collection is full")
            else:
                existing.difference_update(keys)
            target["items"] = sorted(existing)
        _write_locked(state)
        return {"updated": len(keys), "operation": operation, "organization": state}


def forget(kind: str, asset_id: str) -> None:
    """Drop metadata after an explicit media delete, without touching other files."""
    key = _key(kind, asset_id)
    with media_lifecycle._lock:
        state = _read_locked()
        state["favorites"] = [x for x in state["favorites"] if x != key]
        for collection in state["collections"]:
            collection["items"] = [x for x in collection["items"] if x != key]
        _write_locked(state)
