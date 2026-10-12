"""Process-local agent lease diagnostics, intentionally metadata-only.

Can identify another agent-provider holder in this process. A lease held by
chat/media or another process remains unknown until its owner is instrumented.
"""
from contextlib import contextmanager
from threading import RLock
import time
import uuid

_lock = RLock()
_holders = {}
_waiters = {}


@contextmanager
def observed_agent_lease(role="agent"):
    ident = uuid.uuid4().hex
    started = time.monotonic()
    with _lock:
        active = list(_holders.values())
        owner = min(active, key=lambda x: x["since"]) if active else None
        _waiters[ident] = {"role": role, "since": started}
    evidence = {
        "observed_holder_role": owner["role"] if owner else "unknown",
        "observed_holder_age_ms": round((started - owner["since"]) * 1000, 2)
        if owner else None,
        "observed_agent_holders": len(active),
    }
    try:
        yield evidence, ident
    finally:
        with _lock:
            _waiters.pop(ident, None)
            _holders.pop(ident, None)


def acquired_agent_lease(ident, role):
    with _lock:
        _waiters.pop(ident, None)
        _holders[ident] = {"role": role, "since": time.monotonic()}


def agent_lease_snapshot():
    with _lock:
        return {"holders": len(_holders), "waiters": len(_waiters)}
