"""Opt-in, resumable full-chat feeder for the existing single local Qwen worker.

The feeder never invokes inference itself. Its bounded queue applies
backpressure to large histories; the existing worker verifies each source
against the current authoritative chat before writing any extracted fact.
"""
from __future__ import annotations

import queue
import threading
import time

from agent import memory_dashboard, personal_memory as pm
from agent import semantic_personal_memory as smart


def _valid(chat):
    if not isinstance(chat, dict) or not isinstance(chat.get("id"), str):
        return []
    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        return []
    return [
        (ordinal, message["content"])
        for ordinal, message in enumerate(messages)
        if isinstance(message, dict) and message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and len(message["content"]) >= 12
    ]


def _feeder(chats):
    try:
        stream = chats() if callable(chats) else sorted(
            (c for c in chats if isinstance(c, dict)), key=lambda c: float(c.get('updated') or 0))
        for chat in stream:
            if callable(chats):
                with smart._STATE_LOCK: smart._FULL['total'] += len(_valid(chat))
            for ordinal, value in _valid(chat):
                with smart._STATE_LOCK:
                    smart._FULL["examined"] += 1
                if not smart.enabled() or memory_dashboard.paused():
                    return
                if smart._SECRET.search(value):
                    with smart._STATE_LOCK:
                        smart._FULL["skipped"] += 1
                    continue
                chat_id = chat["id"]
                digest = smart._digest(value)
                with pm.LOCK, pm._connect() as conn:
                    pm._schema(conn)
                    smart._schema(conn)
                    allowed = smart._can_learn(conn, chat_id)
                    previous = conn.execute(
                        "SELECT digest FROM smart_observed "
                        "WHERE chat_id=? AND ordinal=?",
                        (chat_id, ordinal),
                    ).fetchone()
                if not allowed or (previous and previous["digest"] == digest):
                    with smart._STATE_LOCK:
                        smart._FULL["skipped"] += 1
                    continue
                from agent import knowledge_memory as km
                km.schedule(chat, ordinal, value)
                key = (chat_id, ordinal, digest)
                while True:
                    if not smart.enabled() or memory_dashboard.paused():
                        return
                    with smart._STATE_LOCK:
                        if key in smart._ENQUEUED:
                            smart._FULL["skipped"] += 1
                            break
                        try:
                            smart._TASKS.put_nowait(key)
                        except queue.Full:
                            pass
                        else:
                            smart._ENQUEUED.add(key)
                            smart._FULL["queued"] += 1
                            smart._STATUS["queued"] = smart._TASKS.qsize()
                            break
                    time.sleep(0.2)
    except Exception as error:
        from agent import knowledge_memory
        knowledge_memory.diagnose('historical_scan', error)
    finally:
        with smart._STATE_LOCK:
            smart._FULL["active"] = False


def start(chats):
    """Return immediately; repeat after interruption to skip observed hashes."""
    if not smart.enabled():
        raise ValueError("Enable local Qwen learning first")
    if memory_dashboard.paused():
        raise ValueError("Resume memory before scanning saved conversations")
    if smart._READER is None or smart._COMPLETE is None:
        raise ValueError("Native Qwen worker is not ready")
    from agent import knowledge_memory as km
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        conn.execute("UPDATE analysis_jobs SET status='pending',error_code=NULL WHERE status='error'")
    total = 0 if callable(chats) else sum(len(_valid(chat)) for chat in chats)
    with smart._STATE_LOCK:
        if smart._FULL["active"]:
            return smart.status()
        smart._FULL.update(
            active=True, total=total, examined=0, queued=0, skipped=0,
        )
    threading.Thread(
        target=_feeder, args=(chats,), daemon=True,
        name="mlx-smart-full-history-feed",
    ).start()
    return smart.status()
