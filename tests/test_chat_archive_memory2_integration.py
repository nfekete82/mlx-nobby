"""Integration of on-device archive with real chat saves and memory prompts."""
from fastapi.testclient import TestClient

from agent import app as agent_app
from agent import chat_archive
from agent import memory


def _chat(chat_id, text):
    return {
        "id": chat_id,
        "title": "Private test",
        "created": 1,
        "updated": 100,
        "revision": 0,
        "messages": [{"role": "user", "content": text}],
        "settings": {"system_prompt": "", "preset_id": "general"},
    }


def test_real_chat_write_indexes_only_after_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_app, "CHAT_DIRECTORY", tmp_path / "chats")
    monkeypatch.setattr(chat_archive, "DB_PATH", tmp_path / "private" / "archive.sqlite3")
    with TestClient(agent_app.app, base_url="http://localhost") as client:
        response = client.put("/api/chats/local-test", json=_chat("local-test", "Sandforge private topic"))
        assert response.status_code == 200
        assert not chat_archive.DB_PATH.exists()

        chat_archive.set_enabled(True)
        response = client.put("/api/chats/local-test", json={
            **_chat("local-test", "Sandforge improved navigation"), "updated": 200,
        })
        assert response.status_code == 200
        assert chat_archive.search("navigation")[0]["chat_id"] == "local-test"
        assert chat_archive.search("private") == []


def test_memory_injects_relevant_sourced_chat_context(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_archive, "DB_PATH", tmp_path / "private" / "archive.sqlite3")
    chat_archive.set_enabled(True)
    chat_archive.index_chat(_chat("project-chat", "Sandforge pathfinding: avoid the cliffs"))
    monkeypatch.setattr(memory, "context", lambda *args, **kwargs: "")
    enriched = memory.enrich_messages(
        [{"role": "user", "content": "What was our Sandforge plan?"}],
        observe=False,
    )
    assert enriched[0]["role"] == "system"
    assert "project-chat" in enriched[0]["content"]
    assert "UNTRUSTED" in enriched[0]["content"]
    assert enriched[-1]["role"] == "user"
