"""Personal memory API and live chat-write integration (synthetic data only)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import app as chat_host
from agent import personal_memory as pm
from agent import memory_lifecycle
from agent.personal_memory_routes import install_routes


@pytest.fixture(autouse=True)
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "private" / "personal.sqlite3")
    monkeypatch.setattr(chat_host, "CHAT_DIRECTORY", tmp_path / "chats")


def chat(chat_id, message, updated=100):
    return {
        "id": chat_id,
        "title": "Test",
        "created": 1,
        "updated": updated,
        "revision": 0,
        "messages": [{"role": "user", "content": message}],
        "settings": {"system_prompt": "", "preset_id": "general"},
    }


def api():
    app = FastAPI()
    install_routes(app, chat_host)
    return TestClient(app)


def test_optin_backfills_real_saved_chats_and_exposes_source():
    with TestClient(chat_host.app) as writer, api() as client:
        saved = writer.put("/api/chats/memory-test", json=chat(
            "memory-test", "Meine Freundin heißt Nora"))
        assert saved.status_code == 200
        assert not pm.DB_PATH.exists()
        response = client.post("/api/personal-memory/config", json={"enabled": True})
        assert response.status_code == 200
        assert response.json()["active_facts"] == 1
        data = client.get("/api/personal-memory/facts").json()["facts"]
        assert data[0]["source_chat_id"] == "memory-test"
        assert data[0]["value"] == "Nora"


def test_live_chat_change_adds_pending_and_user_can_resolve():
    with TestClient(chat_host.app) as writer, api() as client:
        client.post("/api/personal-memory/config", json={"enabled": True})
        r1 = writer.put("/api/chats/a", json=chat("a", "Mein Termin ist am 16. November"))
        r2 = writer.put("/api/chats/b", json=chat("b", "Mein Termin ist am 18. November"))
        assert r1.status_code == 200
        assert r2.status_code == 200
        questions = client.get("/api/personal-memory/conflicts").json()["conflicts"]
        assert len(questions) == 1
        result = client.post("/api/personal-memory/conflicts/" +
                             questions[0]["id"] + "/resolve", json={"decision": "new"})
        assert result.status_code == 200
        assert "18" in client.get("/api/personal-memory/facts").json()["facts"][0]["value"]
        assert len(client.get("/api/personal-memory/conflicts").json()["conflicts"]) == 0


def test_delete_chat_purges_derived_fact_and_keeps_other_chats():
    with TestClient(chat_host.app) as writer, api() as client:
        client.post("/api/personal-memory/config", json={"enabled": True})
        writer.put("/api/chats/a", json=chat("a", "Meine Freundin heißt Kim"))
        assert client.get("/api/personal-memory/facts").json()["facts"]
        assert writer.delete("/api/chats/a").status_code == 200
        assert client.get("/api/personal-memory/facts").json()["facts"] == []


def test_model_is_told_to_ask_about_detected_conflict(monkeypatch):
    pm.set_enabled(True)
    pm.observe("Mein Termin ist am 16. November")
    pm.observe("Mein Termin ist am 18. November")
    from agent import memory
    monkeypatch.setattr(memory, "enrich_messages", lambda msgs, **kwargs: msgs)
    data = memory_lifecycle.enrich_messages(
        [{"role": "user", "content": "Mein Termin ist am 18. November"}],
        observe=False,
    )
    assert any(x["role"] == "system" and "CLARIFICATION REQUIRED" in x["content"]
               for x in data)
    assert any("16" in x["content"] and "18" in x["content"] for x in data
               if x["role"] == "system")
