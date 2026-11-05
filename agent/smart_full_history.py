"""Persistent discovery and resumable analysis using the existing Qwen worker.

Discovery commits work before offering bounded queue wake-ups. A full queue or
an inference failure cannot truncate discovery. Restart rescans authoritative
sources and skips only terminal checkpoints of the current extractor version.
"""
from __future__ import annotations

import json
import queue
import threading
import time

from agent import knowledge_memory as km, memory_dashboard, personal_memory as pm
from agent import semantic_personal_memory as smart

_KEY = 'historical_analysis'
_THREAD = None
_SCAN_LOCK = threading.RLock()


def _valid(chat):
    if not isinstance(chat, dict) or not isinstance(chat.get('id'), str):
        return []
    messages = chat.get('messages', [])
    if not isinstance(messages, list):
        return []
    return [(ordinal, message['content']) for ordinal, message in enumerate(messages)
            if isinstance(message, dict) and message.get('role') == 'user'
            and isinstance(message.get('content'), str) and len(message['content']) >= 12]


def saved_state():
    if not pm.DB_PATH.exists():
        return {}
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        row = conn.execute('SELECT value FROM settings WHERE key=?', (_KEY,)).fetchone()
        return json.loads(row[0]) if row else {}


def _save(**updates):
    with pm.LOCK, pm._connect() as conn:
        pm._schema(conn)
        row = conn.execute('SELECT value FROM settings WHERE key=?', (_KEY,)).fetchone()
        state = json.loads(row[0]) if row else {}
        state.update(updates, updated_at=time.time())
        conn.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (_KEY, json.dumps(state)))
    with smart._STATE_LOCK:
        smart._FULL.update(state)
    return state


def _feeder(chats):
    try:
        stream = chats() if callable(chats) else sorted(
            (c for c in chats if isinstance(c, dict)), key=lambda c: float(c.get('updated') or 0))
        total = examined = queued = skipped = 0
        for chat in stream:
            from agent import chat_archive
            chat_archive.index_chat(chat)
            candidates = _valid(chat)
            total += len(candidates)
            for ordinal, value in candidates:
                if not smart.enabled() or memory_dashboard.paused() or smart._WORKER_STOP.is_set():
                    _save(phase='interrupted', active=False)
                    return
                examined += 1
                with pm.LOCK, pm._connect() as conn:
                    pm._schema(conn)
                    allowed = smart._can_learn(conn, chat['id'])
                    complete = km.observed(conn, chat['id'], ordinal, km.digest(value))
                if not allowed or complete:
                    skipped += 1
                else:
                    # Durable discovery is independent of inference throughput.
                    km.schedule(chat, ordinal, value, historical=True)
                    if km.extraction_skip_reason(value):
                        skipped += 1
                        _save(total=total, examined=examined, queued=queued, skipped=skipped)
                        continue
                    queued += 1
                    key = (chat['id'], ordinal, km.digest(value))
                    with smart._STATE_LOCK:
                        if key not in smart._ENQUEUED:
                            try:
                                smart._TASKS.put_nowait(key)
                            except queue.Full:
                                pass  # worker drains durable jobs after wake-ups
                            else:
                                smart._ENQUEUED.add(key)
                _save(total=total, examined=examined, queued=queued, skipped=skipped)
        _save(phase='scheduled', active=False, discovery_complete=True, error_code=None)
    except Exception as error:
        km.diagnose('historical_scan', error)
        _save(phase='error', active=False, error_code=type(error).__name__)
    finally:
        with smart._STATE_LOCK:
            smart._FULL['active'] = False


def recover(chats):
    """Resume only a previously authorized scan, never opt a user in at startup."""
    state = saved_state()
    if state.get('phase') in ('feeding', 'interrupted') and smart.enabled() and not memory_dashboard.paused():
        return start(chats, retry_errors=False)


def start(chats, *, retry_errors=True):
    global _THREAD
    if not smart.enabled():
        raise ValueError('Enable local Qwen learning first')
    if memory_dashboard.paused():
        raise ValueError('Resume memory before scanning saved conversations')
    if smart._READER is None or smart._COMPLETE is None:
        raise ValueError('Native Qwen worker is not ready')
    with _SCAN_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return smart.status()
        with pm.LOCK, pm._connect() as conn:
            pm._schema(conn)
            if retry_errors:
                conn.execute("UPDATE analysis_jobs SET status='pending',error_code=NULL WHERE status='error' AND version=?", (km.VERSION,))
        _save(active=True, phase='feeding', total=0, examined=0, queued=0, skipped=0,
              discovery_complete=False, error_code=None, version=km.VERSION)
        _THREAD = threading.Thread(target=_feeder, args=(chats,), daemon=True,
                                   name='mlx-smart-full-history-feed')
        _THREAD.start()
    return smart.status()
