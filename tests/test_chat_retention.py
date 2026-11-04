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
