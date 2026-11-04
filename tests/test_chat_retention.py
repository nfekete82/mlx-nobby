"""Opt-in-only deletion, durable revision retention, and scope safety."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from agent import app as agent
from agent import chat_delete_intent, chat_retention


@pytest.fixture()
def local_chats(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CHAT_DIRECTORY", tmp_path / "chats")
    # Never write synthetic tests into real personal/semantic memory databases.
    monkeypatch.setattr(agent.memory_dashboard, "paused", lambda: True)
    return tmp_path / "chats"


def chat(cid="test-chat", text="first message"):
    return {
        "id": cid, "title": "Test", "created": 1, "updated": 2,
        "revision": 0, "messages": [{"role": "user", "content": text}],
    }


def test_refuse_unapproved_delete_reset_and_bulk(local_chats):
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/a", json=chat("a")).status_code == 200
        assert client.delete("/api/chats").status_code == 403
        assert client.delete("/api/chats/a").status_code == 403
        assert client.post("/api/chats/a/reset").status_code == 403
        assert client.get("/api/chats/a").json()["chat"]["messages"][0]["content"] == "first message"
        assert not (local_chats / ".deleted-chat-ids.json").exists()


def test_one_use_scoped_token_requires_explicit_typed_consent():
    with pytest.raises(ValueError):
        chat_delete_intent.issue(scope="all", confirmation="yes")
    token = chat_delete_intent.issue(scope="one", chat_id="a", confirmation="LÖSCHEN")
    assert not chat_delete_intent.consume(scope="one", token=token, chat_id="b")
    assert not chat_delete_intent.consume(scope="one", token=token, chat_id="a")
    token2 = chat_delete_intent.issue(scope="all", confirmation="LÖSCHEN")
    assert chat_delete_intent.consume(scope="all", token=token2)
    assert not chat_delete_intent.consume(scope="all", token=token2)


def test_revision_keeps_older_content_when_edited(local_chats):
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/a", json=chat("a", "first message")).status_code == 200
        old = client.get("/api/chats/a").json()["chat"]
        updated = dict(old)
        updated["messages"] = [{"role": "user", "content": "new edited message"}]
        updated["updated"] += 5
        assert client.put("/api/chats/a", json=updated).status_code == 200
        assert client.get("/api/chats/a").json()["chat"]["messages"][0]["content"] == "new edited message"
    revisions = list((local_chats / ".revisions" / "a").glob("*.json"))
    assert len(revisions) == 1
    assert json.loads(revisions[0].read_text())["messages"][0]["content"] == "first message"
    assert revisions[0].stat().st_mode & 0o777 == 0o600


def test_normal_append_does_not_create_redudant_revision(local_chats):
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/a", json=chat("a")).status_code == 200
        old = client.get("/api/chats/a").json()["chat"]
        updated = dict(old)
        updated["messages"] = old["messages"] + [{"role": "assistant", "content": "reply"}]
        updated["updated"] += 5
        assert client.put("/api/chats/a", json=updated).status_code == 200
    assert not (local_chats / ".revisions" / "a").exists()


def test_deleting_chat_leaves_long_term_revisions_and_source_archive(local_chats):
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/a", json=chat("a")).status_code == 200
        old = client.get("/api/chats/a").json()["chat"]
        updated = dict(old, messages=[{"role": "user", "content": "edited"}],
                       updated=old["updated"] + 5)
        assert client.put("/api/chats/a", json=updated).status_code == 200
        original = local_chats / ".revisions" / "a"
        assert original.is_dir()
        assert client.delete("/api/chats/a").status_code == 403
        assert original.is_dir()
        permit = client.post("/api/chats/delete-intent", json={
            "scope": "one", "chat_id": "a", "confirmation": "LÖSCHEN"
        })
        assert permit.status_code == 200
        token = permit.json()["deletion_token"]
        assert client.request("DELETE", "/api/chats/a", json={
            "deletion_token": token
        }).status_code == 200
        assert original.exists()
    vault = local_chats.parent / "long-term-chat-memory" / "a"
    assert len(list(vault.glob("*.json"))) == 1
    assert json.loads(next(vault.glob("*.json")).read_text())["messages"][0]["content"] == "edited"


def test_symlink_revision_directory_blocks_replacement(tmp_path):
    parent = tmp_path / "chats"
    parent.mkdir()
    chat_file = parent / "a.json"
    chat_file.write_text(json.dumps(chat("a")))
    external = tmp_path / "other"
    external.mkdir()
    (parent / ".revisions").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        chat_retention.preserve_before_overwrite(chat_file, chat("a", "edited"))
    assert not list(external.iterdir())


def test_sidebar_bulk_delete_leaves_long_term_memory_and_source_copies(local_chats, monkeypatch):
    def forbidden_purge(*args, **kwargs):
        raise AssertionError("Bulk chat deletion must never purge memory")
    monkeypatch.setattr(agent.personal_memory, "remove_chat", forbidden_purge)
    monkeypatch.setattr(agent.chat_archive, "remove_chat", forbidden_purge)
    with TestClient(agent.app, base_url="http://localhost") as client:
        for cid in ("a", "b"):
            assert client.put("/api/chats/" + cid, json=chat(cid, "retain " + cid)).status_code == 200
        token = client.post("/api/chats/delete-intent", json={
            "scope": "all", "confirmation": "LÖSCHEN",
        }).json()["deletion_token"]
        result = client.request("DELETE", "/api/chats", json={"deletion_token": token})
        assert result.status_code == 200
        assert client.get("/api/chats").json()["chats"] == []
    for cid in ("a", "b"):
        saved = list((local_chats.parent / "long-term-chat-memory" / cid).glob("*.json"))
        assert len(saved) == 1
        assert json.loads(saved[0].read_text())["messages"][0]["content"] == "retain " + cid


def test_failed_memory_archive_prevents_chat_deletion(local_chats, monkeypatch):
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/a", json=chat("a")).status_code == 200
        def fail_archive(*args, **kwargs):
            raise OSError("simulated unavailable disk")
        monkeypatch.setattr(agent.chat_retention, "preserve_deleted_chat", fail_archive)
        token = client.post("/api/chats/delete-intent", json={
            "scope": "all", "confirmation": "LÖSCHEN",
        }).json()["deletion_token"]
        result = client.request("DELETE", "/api/chats", json={"deletion_token": token})
        assert result.status_code == 500
        assert client.get("/api/chats/a").status_code == 200
        assert not (local_chats / ".deleted-chat-ids.json").exists()


def test_saved_source_is_available_to_memory_after_chat_list_deletion(local_chats, monkeypatch, tmp_path):
    from agent import chat_archive, personal_memory, semantic_personal_memory
    monkeypatch.setattr(personal_memory, "DB_PATH", tmp_path / "private-facts.sqlite3")
    monkeypatch.setattr(chat_archive, "DB_PATH", tmp_path / "chat-index.sqlite3")
    monkeypatch.setattr(agent.memory_dashboard, "paused", lambda: False)
    sample = chat("recall-sample", "Meine Freundin heißt Beispielperson")
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/recall-sample", json=sample).status_code == 200
        permit = client.post("/api/chats/delete-intent", json={
            "scope": "all", "confirmation": "LÖSCHEN"
        }).json()["deletion_token"]
        assert client.request("DELETE", "/api/chats", json={
            "deletion_token": permit
        }).status_code == 200
        assert client.get("/api/chats").json()["chats"] == []

    # History is invisible in the sidebar yet accessible to private memory.
    assert not (local_chats / "recall-sample.json").exists()
    retained = agent.memory_chat_reader("recall-sample")
    assert retained["messages"][0]["content"] == "Meine Freundin heißt Beispielperson"
    sources = list(agent.iter_memory_chats())
    assert len(sources) == 1
    assert sources[0]["id"] == "recall-sample"

    # Independent indexes may be enabled later and rebuilt from the vault.
    personal_memory.set_enabled(True)
    personal_memory.rebuild(sources)
    assert any("Beispielperson" in item["value"]
               for item in personal_memory.list_facts())
    chat_archive.set_enabled(True)
    chat_archive.rebuild(sources)
    assert chat_archive.search("Beispielperson")

    # The local Qwen worker validates archived originals after the UI delete.
    monkeypatch.setattr(semantic_personal_memory, "_READER", agent.memory_chat_reader)
    monkeypatch.setattr(semantic_personal_memory, "_CHAT_LOCK", agent.CHATS_LOCK)
    current = semantic_personal_memory._current("recall-sample", 0)
    assert current is not None and current[0] == "Meine Freundin heißt Beispielperson"


def test_memory_archived_chat_does_not_reappear_in_sidebar(local_chats):
    sample = chat("archived-offscreen", "This long conversation stays privately saved.")
    with TestClient(agent.app, base_url="http://localhost") as client:
        assert client.put("/api/chats/archived-offscreen", json=sample).status_code == 200
        token = client.post("/api/chats/delete-intent", json={
            "scope": "one", "chat_id": "archived-offscreen", "confirmation": "DELETE",
        }).json()["deletion_token"]
        result = client.request("DELETE", "/api/chats/archived-offscreen",
                                json={"deletion_token": token})
        assert result.status_code == 200
        assert agent.memory_chat_reader("archived-offscreen")
        assert client.get("/api/chats").json()["chats"] == []
        assert client.get("/api/chats/archived-offscreen").status_code == 404
