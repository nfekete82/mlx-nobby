import pytest

from agent import memory
from agent import memory_consolidation
from agent import memory_lifecycle


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(memory, "ROOT", root)
    monkeypatch.setattr(memory, "MEMORY_DB", root / "memory.db")
    return root


def test_slot_replacement_keeps_newest_and_preserves_strong_metadata(
    isolated_memory,
):
    old = memory.add(
        "Für Coding nutze ich Qwen3.8-27B.",
        importance=0.95,
        confidence=0.99,
        pinned=True,
    )
    new = memory.add(
        "Für Coding nutze ich Devstral.",
        importance=0.78,
        confidence=0.88,
        pinned=False,
    )

    result = memory_consolidation.consolidate_memory(memory.MEMORY_DB, new["id"])

    assert result["changed"] is True
    assert result["primary_id"] == new["id"]
    assert result["absorbed"][0]["id"] == old["id"]
    assert result["absorbed"][0]["reason"] == "slot_replacement"

    old_after = memory.get(old["id"])
    new_after = memory.get(new["id"])
    assert old_after["enabled"] is False
    assert new_after["enabled"] is True
    assert new_after["pinned"] is True
    assert new_after["importance"] == pytest.approx(0.95)
    assert new_after["confidence"] == pytest.approx(0.99)


def test_semantic_duplicate_is_disabled_but_not_deleted(
    isolated_memory,
    monkeypatch,
):
    old = memory.add(
        "Bitte antworte mir kurz und direkt.",
        category="communication",
    )
    new = memory.add(
        "Ich mag knappe, direkte Antworten.",
        category="communication",
    )
    monkeypatch.setattr(
        memory_consolidation.memory_embeddings,
        "semantic_scores",
        lambda _db, candidates, _query: {
            item["id"]: 0.985 for item in candidates
        },
    )

    result = memory_consolidation.consolidate_memory(memory.MEMORY_DB, new["id"])

    assert result["changed"] is True
    assert result["primary_id"] == new["id"]
    assert result["absorbed"][0]["id"] == old["id"]
    assert result["absorbed"][0]["reason"] == "semantic_duplicate"
    assert result["absorbed"][0]["similarity"] == pytest.approx(0.985)
    assert memory.get(old["id"])["enabled"] is False
    assert memory.get(old["id"])["text"] == "Bitte antworte mir kurz und direkt."
    assert memory.get(new["id"])["enabled"] is True


def test_semantically_distinct_memories_are_kept(
    isolated_memory,
    monkeypatch,
):
    old = memory.add(
        "Bitte antworte mir kurz und direkt.",
        category="communication",
    )
    new = memory.add(
        "Ich möchte technische Antworten auf Deutsch.",
        category="communication",
    )
    monkeypatch.setattr(
        memory_consolidation.memory_embeddings,
        "semantic_scores",
        lambda _db, candidates, _query: {
            item["id"]: 0.50 for item in candidates
        },
    )

    result = memory_consolidation.consolidate_memory(memory.MEMORY_DB, new["id"])

    assert result["changed"] is False
    assert memory.get(old["id"])["enabled"] is True
    assert memory.get(new["id"])["enabled"] is True


def test_lifecycle_consolidates_before_returning_memory(isolated_memory):
    first = memory_lifecycle.observe_user_message(
        "Merk dir: Für Coding nutze ich Qwen3.8-27B."
    )
    second = memory_lifecycle.observe_user_message(
        "Merk dir: Für Coding nutze ich Devstral."
    )

    assert first["action"] == "remembered"
    assert second["action"] == "remembered"
    assert second["consolidation"]["changed"] is True
    assert second["memory"]["text"] == "Für Coding nutze ich Devstral."

    active = memory.list_memories()
    all_items = memory.list_memories(include_disabled=True)
    assert [item["text"] for item in active] == ["Für Coding nutze ich Devstral."]
    assert len(all_items) == 2
    assert sum(not item["enabled"] for item in all_items) == 1


def test_consolidation_events_are_auditable(isolated_memory):
    old = memory.add("Nenn mich Norbert.", pinned=True)
    new = memory.add("Nenn mich Nobby.", pinned=True)

    memory_consolidation.consolidate_memory(memory.MEMORY_DB, new["id"])
    events = memory_consolidation.list_events(memory.MEMORY_DB)
    status = memory_consolidation.status(memory.MEMORY_DB)

    assert len(events) == 1
    assert events[0]["primary_memory_id"] == new["id"]
    assert events[0]["absorbed_memory_id"] == old["id"]
    assert events[0]["primary_text"] == "Nenn mich Nobby."
    assert events[0]["absorbed_text"] == "Nenn mich Norbert."
    assert events[0]["reason"] == "slot_replacement"
    assert status["events"] == 1
    assert status["disabled_memories"] == 1


def test_explicit_forget_purges_disabled_history_and_audit(isolated_memory):
    first = memory_lifecycle.observe_user_message(
        "Merk dir: Für Coding nutze ich Qwen3.8-27B."
    )
    second = memory_lifecycle.observe_user_message(
        "Merk dir: Für Coding nutze ich Devstral."
    )

    assert second["consolidation"]["changed"] is True
    assert len(memory.list_memories(include_disabled=True)) == 2
    assert len(memory_consolidation.list_events(memory.MEMORY_DB)) == 1

    forgotten = memory_lifecycle.observe_user_message("Vergiss Devstral Coding")

    assert forgotten["action"] == "forgot"
    assert forgotten["count"] == 1
    assert set(forgotten["privacy_cleanup"]["memory_ids"]) == {
        first["remembered_memory_id"],
        second["remembered_memory_id"],
    }
    assert memory.list_memories(include_disabled=True) == []
    assert memory_consolidation.list_events(memory.MEMORY_DB) == []
