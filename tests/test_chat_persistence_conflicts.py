"""Stale browser tabs must not overwrite another tab's persisted chats."""
from unittest.mock import patch

from fastapi.testclient import TestClient
from agent import app as agent


def record(chat_id, updated, text):
    return {
        "id": chat_id,
        "title": "Test",
        "created": 1,
        "updated": updated,
        "revision": 0,
        "messages": [{"role": "user", "content": text}],
    }


def test_new_chat_compare_and_swap_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    with TestClient(agent.app, base_url='http://localhost') as client:
        first = record("shared-chat", 10, "Initial")
        assert client.put("/api/chats/shared-chat",
                          json=first | {"expected_updated": -1}).status_code == 200

        # Two tabs both read updated=10.
        winner = record("shared-chat", 20, "From tab A")
        saved = client.put("/api/chats/shared-chat",
                           json=winner | {"expected_updated": 10})
        assert saved.status_code == 200
        assert saved.json()["conflict"] is False

        stale = record("shared-chat", 30, "From stale tab B")
        refused = client.put("/api/chats/shared-chat",
                             json=stale | {"expected_updated": 10})
        assert refused.status_code == 200
        assert refused.json()["conflict"] is True
        assert refused.json()["chat"]["messages"] == winner["messages"]
        assert agent.read_chat("shared-chat")["messages"] == winner["messages"]
        assert agent.read_chat("shared-chat")["updated"] == 20

        # A stale cache cannot introduce an existing chat as if it were new.
        exists = client.put("/api/chats/shared-chat",
                            json=stale | {"expected_updated": -1})
        assert exists.status_code == 200
        assert exists.json()["conflict"] is True
        assert agent.read_chat("shared-chat")["updated"] == 20

        # A missing chat cannot be silently created by an outdated tab.
        missing = client.put("/api/chats/missing-chat",
                             json=record("missing-chat", 40, "Stale") |
                                 {"expected_updated": 10})
        assert missing.status_code == 409
        assert agent.read_chat("missing-chat") is None


def test_identical_chat_put_is_no_op_and_legacy_clients_still_work(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    with TestClient(agent.app, base_url='http://localhost') as client:
        payload = record("legacy-compatible", 10, "Same")
        assert client.put("/api/chats/legacy-compatible", json=payload).status_code == 200

        with patch.object(agent, "write_chat", side_effect=AssertionError("unnecessary disk write")):
            response = client.put("/api/chats/legacy-compatible", json=payload)
            assert response.status_code == 200
            assert response.json()["conflict"] is False

        # Legacy clients may omit the optional guard. Existing timestamp
        # ordering still prevents older writes even without CAS metadata.
        changed = record("legacy-compatible", 20, "Newer")
        assert client.put("/api/chats/legacy-compatible", json=changed).status_code == 200
        outdated = record("legacy-compatible", 15, "Old")
        response = client.put("/api/chats/legacy-compatible", json=outdated)
        assert response.status_code == 200
        assert response.json()["conflict"] is True
        assert agent.read_chat("legacy-compatible")["messages"] == changed["messages"]
