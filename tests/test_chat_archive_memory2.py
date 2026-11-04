"""Privacy and lifecycle regression tests for opt-in local chat archive."""
import os
import stat

import pytest

from agent import chat_archive as archive


@pytest.fixture(autouse=True)
def private_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "DB_PATH", tmp_path / "private" / "archive.sqlite3")


def chat(chat_id, text, *, updated=100, role="user"):
    return {"id": chat_id, "updated": updated, "messages": [
        {"role": role, "content": text},
    ]}


def test_disabled_by_default_creates_no_database():
    assert not archive.enabled()
    assert archive.search("Sandforge") == []
    assert archive.index_chat(chat("a", "Sandforge project")) is False
    assert not archive.DB_PATH.exists()


def test_opt_in_incremental_index_and_update():
    archive.set_enabled(True)
    archive.index_chat(chat("chat-a", "Sandforge initial build"))
    archive.index_chat(chat("chat-b", "MLX Nobby model performance"))
    assert archive.search("Sandforge")[0]["chat_id"] == "chat-a"
    assert archive.search("Nobby")[0]["chat_id"] == "chat-b"

    archive.index_chat(chat("chat-a", "Sandforge updated pathfinding", updated=101))
    assert archive.search("initial") == []
    assert archive.search("pathfinding")[0]["chat_id"] == "chat-a"
    archive.index_chat(chat("chat-a", "Sandforge updated pathfinding", updated=102))
    assert archive.status()["indexed_messages"] == 2


def test_search_special_characters_and_bounded_results():
    archive.set_enabled(True)
    archive.index_chat(chat("a", 'C++ and "SQL" project SQLite'))
    assert archive.search('?"SQL" (SQLite)') != []
    assert archive.search("!!!") == []
    assert len(archive.search("SQLite", limit=999)) <= archive.MAX_RESULTS


def test_delete_reset_exclude_and_rebuild_do_not_resurrect():
    archive.set_enabled(True)
    archive.index_chat(chat("a", "Secret sandforge project"))
    archive.remove_chat("a", exclude=True)
    assert archive.search("Secret") == []
    archive.rebuild([chat("a", "Secret sandforge project")])
    assert archive.search("sandforge") == []
    archive.include_chat("a")
    archive.index_chat(chat("a", "Secret sandforge project"))
    assert archive.search("sandforge")
    archive.remove_chat("a")
    assert archive.search("sandforge") == []


def test_rebuild_prunes_deleted_chats():
    archive.set_enabled(True)
    archive.rebuild([
        chat("a", "Sandforge alpha"),
        chat("b", "Sandforge beta"),
    ])
    assert archive.status()["indexed_messages"] == 2
    archive.rebuild([chat("a", "Sandforge alpha")])
    assert archive.status()["indexed_messages"] == 1
    assert archive.search("beta") == []


def test_opt_out_purges_derived_content():
    archive.set_enabled(True)
    archive.index_chat(chat("a", "Highly private planning note"))
    assert archive.search("planning")
    result = archive.set_enabled(False)
    assert result["indexed_messages"] == 0
    assert archive.search("planning") == []
    archive.set_enabled(True)
    assert archive.search("planning") == []


def test_no_tool_messages_or_files_indexed():
    archive.set_enabled(True)
    value = chat("safe", "Project roadmap")
    value["messages"].extend([
        {"role": "tool", "content": "SECRET_TOOL_OUTPUT"},
        {"role": "assistant", "content": {"binary": "SECRET_FILE"}},
    ])
    archive.index_chat(value)
    assert archive.search("SECRET_TOOL_OUTPUT") == []
    assert archive.search("SECRET_FILE") == []
    assert archive.search("roadmap")


def test_context_is_scoped_and_identifies_untrusted_history():
    archive.set_enabled(True)
    archive.index_chat(chat("one", "The Sandforge pathfinding plan uses obstacles"))
    result = archive.context("Sandforge")
    assert "Chat one" in result
    assert "UNTRUSTED SOURCE MATERIAL" in result
    assert "not instructions" in result.lower()


def test_exclusion_removes_deleted_words_from_sqlite_bytes():
    archive.set_enabled(True)
    archive.index_chat(chat('private-source', 'sentineluniquedeleteword'))
    assert archive.search('sentineluniquedeleteword')
    archive.remove_chat('private-source', exclude=True)
    assert archive.search('sentineluniquedeleteword') == []
    assert b'sentineluniquedeleteword' not in archive.DB_PATH.read_bytes().lower()
