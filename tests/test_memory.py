from pathlib import Path

import pytest

from agent import memory
from agent.model_provider import ModelRequest, _with_memory


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(memory, "ROOT", root)
    monkeypatch.setattr(memory, "MEMORY_DB", root / "memory.db")
    monkeypatch.setattr(
        memory.memory_embeddings,
        "semantic_scores",
        lambda *_args, **_kwargs: None,
    )
    return root


def test_explicit_remember_is_persisted_and_deduplicated(isolated_memory):
    first = memory.observe_user_message(
        "Merk dir: Für Coding nutze ich Qwen3.8-27B.",
        source_chat_id="chat-a",
    )
    second = memory.observe_user_message(
        "Merk dir: Für Coding nutze ich Qwen3.8-27B.",
        source_chat_id="chat-a",
    )

    assert first["action"] == "remembered"
    assert second["action"] == "remembered"
    items = memory.list_memories()
    assert len(items) == 1
    assert items[0]["pinned"] is True
    assert items[0]["source_chat_id"] == "chat-a"


def test_ordinary_chat_is_not_automatically_stored(isolated_memory):
    result = memory.observe_user_message(
        "Kannst du mir den Unterschied zwischen TCP und UDP erklären?"
    )

    assert result == {"action": "ignored"}
    assert memory.list_memories() == []


def test_durable_preference_is_detected_conservatively(isolated_memory):
    result = memory.observe_user_message(
        "Ich bevorzuge Qwen Image 2.1 für Bildgenerierung."
    )

    assert result["action"] == "remembered"
    assert result["memory"]["category"] == "ai_models"
    assert result["memory"]["pinned"] is False


def test_retrieval_prefers_query_relevant_memory(isolated_memory):
    memory.add(
        "Für Coding nutze ich Qwen3.8-27B.",
        category="coding",
        importance=0.8,
    )
    memory.add(
        "Für Bildgenerierung bevorzuge ich Qwen Image 2.1.",
        category="ai_models",
        importance=0.8,
    )

    selected = memory.retrieve("Welches Modell soll ich fürs Coding nehmen?", limit=1)

    assert len(selected) == 1
    assert "Qwen3.8-27B" in selected[0]["text"]


def test_semantic_retrieval_finds_memory_without_keyword_overlap(
    isolated_memory,
    monkeypatch,
):
    coding = memory.add(
        "Für Coding nutze ich Qwen3.8-27B.",
        category="coding",
        importance=0.8,
    )
    image = memory.add(
        "Für Bildgenerierung bevorzuge ich Qwen Image 2.1.",
        category="ai_models",
        importance=0.8,
    )

    monkeypatch.setattr(
        memory.memory_embeddings,
        "semantic_scores",
        lambda _db, _memories, _query: {
            coding["id"]: 0.91,
            image["id"]: 0.10,
        },
    )

    selected = memory.retrieve(
        "Welche KI nehme ich zum Programmieren?",
        limit=1,
    )

    assert len(selected) == 1
    assert selected[0]["id"] == coding["id"]


def test_semantic_noise_below_threshold_is_not_injected(
    isolated_memory,
    monkeypatch,
):
    unrelated = memory.add(
        "Für Bildgenerierung bevorzuge ich Qwen Image 2.1.",
        importance=1.0,
    )
    monkeypatch.setattr(
        memory.memory_embeddings,
        "semantic_scores",
        lambda _db, _memories, _query: {unrelated["id"]: 0.20},
    )

    selected = memory.retrieve("Wie konfiguriere ich eine Firewall?", limit=4)

    assert selected == []


def test_pinned_memory_can_be_retrieved_without_keyword_overlap(isolated_memory):
    memory.add(
        "Nenn mich Nobby.",
        category="communication",
        pinned=True,
    )

    selected = memory.retrieve("Erkläre mir Docker Networking", limit=4)

    assert any(item["text"] == "Nenn mich Nobby." for item in selected)


def test_forget_removes_matching_memory(isolated_memory):
    memory.observe_user_message("Merk dir: Für Coding nutze ich Qwen3.8-27B.")

    result = memory.observe_user_message("Vergiss Qwen3.8-27B Coding")

    assert result["action"] == "forgot"
    assert result["count"] == 1
    assert memory.list_memories() == []


def test_enrich_messages_injects_bounded_memory_context(isolated_memory):
    memory.add(
        "Für Coding nutze ich Qwen3.8-27B.",
        category="coding",
        pinned=True,
    )
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hilf mir beim Coding."},
    ]

    enriched = memory.enrich_messages(messages, observe=False)

    assert messages == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hilf mir beim Coding."},
    ]
    assert enriched[1]["role"] == "system"
    assert "RELEVANT LONG-TERM USER MEMORY" in enriched[1]["content"]
    assert "Qwen3.8-27B" in enriched[1]["content"]


def test_model_provider_memory_hook_skips_strict_json_prompt(isolated_memory):
    memory.add("Nenn mich Nobby.", pinned=True)
    request = ModelRequest(
        messages=[
            {
                "role": "system",
                "content": "Return exactly one JSON object and nothing else.",
            },
            {"role": "user", "content": "Plane etwas."},
        ],
        role="agent",
    )

    enriched = _with_memory(request, None)

    assert enriched is request


def test_model_provider_memory_hook_enriches_normal_agent_prompt(isolated_memory):
    memory.add("Nenn mich Nobby.", pinned=True)
    request = ModelRequest(
        messages=[
            {"role": "system", "content": "Help the user."},
            {"role": "user", "content": "Erkläre mir Git branches."},
        ],
        role="agent",
    )

    enriched = _with_memory(request, None)

    assert enriched is not request
    assert any(
        message.get("role") == "system"
        and "Nenn mich Nobby." in message.get("content", "")
        for message in enriched.messages
    )
