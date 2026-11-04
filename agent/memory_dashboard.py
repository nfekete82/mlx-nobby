"""Local, non-destructive pause and read-only inventory for Nobby Memory.

The pause flag is a small owner-only file outside Git. Pausing stops automatic
recall/extraction and incremental indexing; it never deletes chat files,
legacy memories, private facts or search indices. Inspect/edit/delete APIs
remain available while paused so the user stays in control.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from agent import chat_archive, memory, personal_memory

STATE_PATH = Path.home() / ".config/mlx-web/memory-control.json"
LOCK = threading.RLock()
SOURCES = ("personal", "legacy", "archive")
MAX_PAGE = 50


def paused() -> bool:
    if not STATE_PATH.exists():
        return False
    try:
        with LOCK:
            payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload.get("paused") is True
    except (OSError, ValueError, TypeError):
        # A damaged configuration must not accidentally re-enable recall.
        return True


def set_paused(value: bool) -> dict:
    if type(value) is not bool:
        raise ValueError("paused must be a boolean")
    with LOCK:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(prefix=".memory-control-", dir=STATE_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump({"paused": value}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, STATE_PATH)
            os.chmod(STATE_PATH, 0o600)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return {"paused": value}


def _count(path, connect, schema, sql) -> int:
    if not path.exists():
        return 0
    with connect() as conn:
        schema(conn)
        return int(conn.execute(sql).fetchone()[0])


def status() -> dict:
    return {
        "paused": paused(),
        "counts": {
            "personal": _count(
                personal_memory.DB_PATH, personal_memory._connect,
                personal_memory._schema, "SELECT COUNT(*) FROM facts WHERE status='active'",
            ),
            "legacy": _count(
                memory.MEMORY_DB, memory._connect, memory._ensure_schema,
                "SELECT COUNT(*) FROM memories",
            ),
            "archive": _count(
                chat_archive.DB_PATH, chat_archive._connect, chat_archive._schema,
                "SELECT COUNT(*) FROM archive_messages",
            ),
        },
        "layers": {
            "personal": personal_memory.enabled(),
            "archive": chat_archive.enabled(),
        },
    }


def _escape_like(query: str) -> str:
    return "%" + str(query or "").strip()[:150].replace(
        "\\", "\\\\"
    ).replace("%", "\\%").replace("_", "\\_") + "%"


def list_items(source: str, *, query: str = "", offset: int = 0, limit: int = 20) -> dict:
    if source not in SOURCES:
        raise ValueError("unknown memory source")
    bounded = max(1, min(int(limit), MAX_PAGE))
    start = max(0, min(int(offset), 1_000_000))
    if source == "personal":
        path, connect, schema = (
            personal_memory.DB_PATH, personal_memory._connect, personal_memory._schema
        )
        cols = ("id,subject,field,value,sensitive,source_chat_id,source_ordinal,"
                "status,updated_at")
        table = "facts"
        clause = "subject LIKE ? ESCAPE '\\' OR field LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\'"
        args = (_escape_like(query),) * 3
        order = "updated_at DESC,id DESC"
    elif source == "legacy":
        path, connect, schema = memory.MEMORY_DB, memory._connect, memory._ensure_schema
        cols = ("id,text,category,source_chat_id,pinned,enabled,"
                "importance,confidence,updated_at")
        table = "memories"
        clause = "text LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\'"
        args = (_escape_like(query),) * 2
        order = "updated_at DESC,id DESC"
    else:
        path, connect, schema = (
            chat_archive.DB_PATH, chat_archive._connect, chat_archive._schema
        )
        cols = ("chat_id,ordinal,role,content,updated")
        table = "archive_messages"
        clause = "content LIKE ? ESCAPE '\\' OR chat_id LIKE ? ESCAPE '\\'"
        args = (_escape_like(query),) * 2
        order = "updated DESC,id DESC"
    if not path.exists():
        return {"source": source, "items": [], "total": 0, "offset": start}
    with connect() as conn:
        schema(conn)
        where = f"WHERE ({clause})"
        total = int(conn.execute(
            f"SELECT COUNT(*) FROM {table} {where}", args
        ).fetchone()[0])
        rows = conn.execute(
            f"SELECT {cols} FROM {table} {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*args, bounded, start),
        ).fetchall()
        items = [dict(row) for row in rows]
    return {"source": source, "items": items, "total": total, "offset": start}
