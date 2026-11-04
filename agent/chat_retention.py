"""Private revisions for chat edits which would otherwise discard history.

The current chat JSON remains the authoritative active chat. If a saved user
message is edited, a message is removed, or assistant text shrinks, preserve
the previous full chat before replacing it. No TTL or automatic cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import uuid


def _destructive_change(before: dict, after: dict) -> bool:
    previous = before.get("messages", [])
    current = after.get("messages", [])
    if not isinstance(previous, list) or not isinstance(current, list):
        return False
    if len(current) < len(previous):
        return True
    for old, new in zip(previous, current):
        if not isinstance(old, dict) or not isinstance(new, dict):
            return True
        if old.get("role") != new.get("role"):
            return True
        earlier, later = old.get("content"), new.get("content")
        if isinstance(earlier, str):
            if not isinstance(later, str):
                return True
            if old.get("role") == "user" and earlier != later:
                return True
            if old.get("role") == "assistant" and not later.startswith(earlier):
                return True
    return False


def preserve_before_overwrite(chat_path: Path, replacement: dict) -> bool:
    """Write an owner-only revision *before* mutating the current chat JSON."""
    if not chat_path.exists():
        return False
    if chat_path.is_symlink() or not chat_path.is_file():
        raise ValueError("Unsafe chat path")
    previous = json.loads(chat_path.read_text(encoding="utf-8"))
    if not _destructive_change(previous, replacement):
        return False
    parent = chat_path.parent / ".revisions"
    if parent.is_symlink():
        raise ValueError("Unsafe revision root")
    parent.mkdir(mode=0o700, exist_ok=True)
    folder = parent / chat_path.stem
    if folder.is_symlink():
        raise ValueError("Unsafe revision folder")
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / (uuid.uuid4().hex + ".json")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(previous, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    return True


def remove_revisions(chat_directory: Path, chat_id: str) -> None:
    """Called only after an explicitly authorized settings deletion."""
    base = chat_directory / ".revisions"
    if base.is_symlink():
        raise ValueError("Unsafe revision root")
    target = base / chat_id
    if target.is_symlink():
        raise ValueError("Unsafe revision folder")
    if target.exists():
        shutil.rmtree(target)
