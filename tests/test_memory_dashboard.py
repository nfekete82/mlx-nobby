"""Regression tests for simplified on-device memory dashboard (synthetic data only)."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import chat_archive, memory, memory_dashboard, memory_lifecycle, personal_memory
from agent.memory_dashboard_routes import install_routes


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_dashboard, "STATE_PATH", tmp_path / "control.json")
    monkeypatch.setattr(memory, "ROOT", tmp_path)
    monkeypatch.setattr(memory, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(personal_memory, "DB_PATH", tmp_path / "personal.sqlite3")
    monkeypatch.setattr(chat_archive, "DB_PATH", tmp_path / "archive.sqlite3")


def fake_chat(chat_id, text):
    return {"id": chat_id, "updated": 100, "messages": [{"role": "user", "content": text}]}


def test_pause_does_not_delete_any_layer_and_survives_restart():
    memory.add("I prefer local offline models")
    personal_memory.set_enabled(True)
    personal_memory.index_chat(fake_chat("a", "Meine Freundin heißt Testname"))
    chat_archive.set_enabled(True)
    chat_archive.index_chat(fake_chat("a", "Synthetic archive fact"))
    original = memory_dashboard.status()
    assert original["counts"] == {"personal": 1, "legacy": 1, "archive": 1}
    assert memory_dashboard.paused() is False

    assert memory_dashboard.set_paused(True)["paused"] is True
    assert memory_dashboard.paused() is True
    assert memory_dashboard.status()["counts"] == original["counts"]
    assert memory_dashboard.STATE_PATH.stat().st_mode & 0o777 == 0o600
    assert memory_lifecycle.observe_user_message("Merke dir: should remain unstored") == {
        "action": "paused"
    }
    message = {"role": "user", "content": "What did we discuss?"}
    assert memory_lifecycle.enrich_messages([message]) == [message]
    assert memory_dashboard.set_paused(False)["paused"] is False
    assert memory_dashboard.status()["counts"] == original["counts"]


def test_inventory_pages_all_stores_without_returning_everything_at_once():
    for num in range(34):
        memory.add(f"synthetic memory item {num}")
    personal_memory.set_enabled(True)
    personal_memory.index_chat(fake_chat("x", "Meine Freundin heißt Fictional"))
    chat_archive.set_enabled(True)
    chat_archive.index_chat(fake_chat("x", "Private synthetic message for indexing"))
    first = memory_dashboard.list_items("legacy", limit=20)
    second = memory_dashboard.list_items("legacy", offset=20, limit=20)
    assert len(first["items"]) == 20
    assert len(second["items"]) == 14
    assert first["total"] == second["total"] == 34
    assert set(row["id"] for row in first["items"]).isdisjoint(
        row["id"] for row in second["items"]
    )
    assert memory_dashboard.list_items("personal")["items"][0]["source_chat_id"] == "x"
    assert memory_dashboard.list_items("archive")["items"][0]["chat_id"] == "x"
    assert memory_dashboard.list_items("legacy", query="item 33")["total"] == 1
    assert memory_dashboard.list_items("archive", query="synthetic")["total"] == 1
    assert memory_dashboard.list_items("personal", query="Fictional")["total"] == 1


def test_dashboard_api_preserves_state_on_pause_and_rejects_bad_inputs():
    app = FastAPI()
    install_routes(app)
    with TestClient(app) as client:
        assert client.get("/api/memory-dashboard/status").json()["paused"] is False
        assert client.post("/api/memory-dashboard/pause", json={"paused": "false"}).status_code == 422
        assert client.post("/api/memory-dashboard/pause", json={"paused": True}).json()["paused"]
        assert client.get("/api/memory-dashboard/status").json()["paused"]
        assert client.get("/api/memory-dashboard/items", params={"source": "invalid"}).status_code == 422
        assert client.post("/api/memory-dashboard/pause", json={"paused": False}).status_code == 200


def test_no_state_file_created_by_read_only_dashboard_calls():
    assert memory_dashboard.paused() is False
    status = memory_dashboard.status()
    assert status["counts"] == {"personal": 0, "legacy": 0, "archive": 0}
    assert memory_dashboard.list_items("personal")["items"] == []
    assert not memory_dashboard.STATE_PATH.exists()
    assert not personal_memory.DB_PATH.exists()
    assert not chat_archive.DB_PATH.exists()
