"""Short-lived, single-use authorization for destructive chat operations.

Only an explicit settings confirmation may issue a permit. The permit never
persists across a restart and cannot be reused for another scope/chat.
"""
from __future__ import annotations

import secrets
import threading
import time


_LOCK = threading.Lock()
_PENDING: dict[str, tuple[str, str | None, float]] = {}
_TTL_SECONDS = 90
_ALLOWED_SCOPES = {"all", "one", "reset"}


def issue(*, scope: str, confirmation: str, chat_id: str | None = None) -> str:
    if scope not in _ALLOWED_SCOPES:
        raise ValueError("Invalid chat deletion scope")
    if scope == "all" and chat_id is not None:
        raise ValueError("Bulk deletion cannot target one chat")
    if scope != "all" and (not isinstance(chat_id, str) or not chat_id):
        raise ValueError("A chat ID is required")
    # This is a deliberate typed consent, not a reusable configuration switch.
    if confirmation != "LÖSCHEN" and confirmation != "DELETE":
        raise ValueError("Type LÖSCHEN or DELETE in Settings to authorize deletion")
    with _LOCK:
        now = time.monotonic()
        for key, record in list(_PENDING.items()):
            if record[2] <= now:
                _PENDING.pop(key, None)
        token = secrets.token_urlsafe(32)
        _PENDING[token] = (scope, chat_id, now + _TTL_SECONDS)
    return token


def consume(*, scope: str, token: object, chat_id: str | None = None) -> bool:
    if not isinstance(token, str) or not token:
        return False
    with _LOCK:
        saved = _PENDING.pop(token, None)
    return bool(saved and saved[0] == scope and saved[1] == chat_id
                and saved[2] > time.monotonic())
