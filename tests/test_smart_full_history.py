"""Full-history feeder tests use fictional chats and a private test database."""
from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest

from agent import memory_dashboard
from agent import personal_memory as pm
from agent import semantic_personal_memory as smart
from agent import smart_full_history


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "facts.sqlite3")
    monkeypatch.setattr(memory_dashboard, "STATE_PATH", tmp_path / "pause.json")
    monkeypatch.setattr(smart, "_TASKS", queue.Queue(maxsize=10))
    monkeypatch.setattr(smart, "_ENQUEUED", set())
    monkeypatch.setattr(
        smart, "_FULL",
        {"active": False, "total": 0, "examined": 0, "queued": 0, "skipped": 0},
    )
    monkeypatch.setattr(smart, "_STATUS", {"queued": 0, "processed": 0, "failed": 0})
    monkeypatch.setattr(smart, "_READER", lambda chat_id: None)
    monkeypatch.setattr(smart, "_COMPLETE", lambda prompt: '{"facts":[]}')


def _chats():
    return [
        {"id": "test-a", "updated": 10, "messages": [
            {"role": "user", "content": "Meine Testfigur heißt Mira."},
            {"role": "assistant", "content": "Verstanden."},
        ]},
        {"id": "test-b", "updated": 20, "messages": [
            {"role": "user", "content": "Mein fiktives Projekt heißt Turm."},
            {"role": "user", "content": "Ich habe eine Vorliebe für blaue Farben."},
        ]},
    ]


def test_full_scan_requires_explicit_optin_and_never_creates_private_db():
    with pytest.raises(ValueError, match="Enable"):
        smart_full_history.start(_chats())
    assert not pm.DB_PATH.exists()


def test_full_scan_queues_all_user_turns_without_duplicate_assistant(monkeypatch):
    pm.set_enabled(True)
    smart.set_enabled(True)

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(
        smart_full_history, "threading",
        SimpleNamespace(Thread=ImmediateThread),
    )
    result = smart_full_history.start(_chats())
    assert result["full_scan"]["total"] == 3
    assert result["full_scan"]["examined"] == 3
    assert result["full_scan"]["queued"] == 3
    assert result["full_scan"]["active"]  # queued durable work is still outstanding
    assert not result["full_scan"]["feeding"]
    assert smart._TASKS.qsize() == 3
    ids = {smart._TASKS.get_nowait()[:2] for _ in range(3)}
    assert ids == {("test-a", 0), ("test-b", 0), ("test-b", 1)}


def test_disabled_scan_stops_early(monkeypatch):
    pm.set_enabled(True)
    smart.set_enabled(True)

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(smart_full_history, "threading",
                        SimpleNamespace(Thread=ImmediateThread))
    memory_dashboard.set_paused(True)
    with pytest.raises(ValueError, match="Resume"):
        smart_full_history.start(_chats())
    assert smart._TASKS.empty()
