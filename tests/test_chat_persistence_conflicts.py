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



def test_equal_millisecond_edits_cannot_beat_compare_and_swap(tmp_path, monkeypatch):
    """Timestamp ties must not let a second tab overwrite a first tab's edit."""
    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    with TestClient(agent.app, base_url="http://localhost") as client:
        base = record("same-millisecond", 1000, "Initial")
        assert client.put(
            "/api/chats/same-millisecond", json=base | {"expected_updated": -1}
        ).status_code == 200

        first = record("same-millisecond", 1000, "First tab's update")
        response = client.put(
            "/api/chats/same-millisecond", json=first | {"expected_updated": 1000}
        )
        assert response.status_code == 200
        assert response.json()["conflict"] is False
        assert response.json()["chat"]["updated"] > 1000

        second = record("same-millisecond", 1000, "Second tab's stale update")
        response = client.put(
            "/api/chats/same-millisecond", json=second | {"expected_updated": 1000}
        )
        assert response.status_code == 200
        assert response.json()["conflict"] is True
        current = agent.read_chat("same-millisecond")
        assert current["messages"] == first["messages"]
        assert current["updated"] > 1000


def test_parallel_cas_writes_and_fork_survive_disk_reload(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import json
    import threading

    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    with TestClient(agent.app, base_url="http://localhost") as client:
        original = record("parallel-shared", 100, "Base")
        assert client.put("/api/chats/parallel-shared", json=original | {
            "expected_updated": -1,
        }).status_code == 200
        barrier = threading.Barrier(2)

        def save(text):
            barrier.wait(timeout=5)
            payload = record("parallel-shared", 101, text)
            response = client.put("/api/chats/parallel-shared", json=payload | {
                "expected_updated": 100,
            })
            assert response.status_code == 200
            return payload, response.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ["Tab A", "Tab B"]))
        assert sorted(result["conflict"] for _, result in results) == [False, True]
        loser = next(payload for payload, result in results if result["conflict"])
        winner = next(payload for payload, result in results if not result["conflict"])
        fork = loser | {"id": "parallel-fork", "title": "Conflict copy"}
        saved = client.put("/api/chats/parallel-fork", json=fork | {"expected_updated": -1})
        assert saved.status_code == 200
        assert saved.json()["conflict"] is False
        for chat_id, expected in [("parallel-shared", winner), ("parallel-fork", loser)]:
            disk = json.loads((agent.CHAT_DIRECTORY / f"{chat_id}.json").read_text())
            assert disk["messages"] == expected["messages"]
            assert client.get(f"/api/chats/{chat_id}").json()["chat"]["messages"] == expected["messages"]
        assert len(client.get("/api/chats").json()["chats"]) == 2


def test_legacy_same_millisecond_edit_invalidates_guarded_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    with TestClient(agent.app, base_url="http://localhost") as client:
        base = record("legacy-race", 100, "Base")
        client.put("/api/chats/legacy-race", json=base | {"expected_updated": -1})
        legacy = record("legacy-race", 100, "Legacy edit")
        accepted = client.put("/api/chats/legacy-race", json=legacy)
        assert accepted.status_code == 200
        assert accepted.json()["chat"]["updated"] > 100
        stale = record("legacy-race", 101, "Guarded stale edit")
        refused = client.put("/api/chats/legacy-race", json=stale | {"expected_updated": 100})
        assert refused.json()["conflict"] is True
        assert agent.read_chat("legacy-race")["messages"] == legacy["messages"]
