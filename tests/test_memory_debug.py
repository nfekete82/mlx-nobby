import pytest

from agent import memory
from agent import memory_debug


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


def test_inspector_uses_lexical_fallback_without_touching_usage(isolated_memory):
    coding = memory.add(
        "Für Coding nutze ich Qwen3.8-27B.",
        category="coding",
        importance=0.8,
    )
    memory.add(
        "Für Bildgenerierung bevorzuge ich Qwen Image 2.1.",
        category="ai_models",
        importance=0.8,
    )

    before = memory.get(coding["id"])
    result = memory_debug.inspect("Welches Modell nutze ich fürs Coding?", limit=1)
    after = memory.get(coding["id"])

    assert result["mode"] == "lexical"
    assert result["selected"][0]["memory"]["id"] == coding["id"]
    assert result["selected"][0]["semantic"] is None
    assert result["selected"][0]["lexical"] > 0
    assert "Qwen3.8-27B" in result["context"]
    assert after["use_count"] == before["use_count"] == 0
    assert after["last_used_at"] == before["last_used_at"] is None


def test_inspector_explains_hybrid_semantic_selection(isolated_memory, monkeypatch):
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

    result = memory_debug.inspect(
        "Welche KI nehme ich zum Programmieren?",
        limit=1,
    )
    selected = result["selected"][0]

    assert result["mode"] == "hybrid"
    assert selected["memory"]["id"] == coding["id"]
    assert selected["semantic"] == pytest.approx(0.91)
    assert selected["contributions"]["semantic"] == pytest.approx(0.91 * 0.58)
    assert selected["score"] > selected["contributions"]["semantic"]


def test_inspector_filters_low_semantic_noise(isolated_memory, monkeypatch):
    unrelated = memory.add(
        "Für Bildgenerierung bevorzuge ich Qwen Image 2.1.",
        importance=1.0,
    )
    monkeypatch.setattr(
        memory.memory_embeddings,
        "semantic_scores",
        lambda _db, _memories, _query: {unrelated["id"]: 0.20},
    )

    result = memory_debug.inspect("Wie konfiguriere ich eine Firewall?", limit=6)

    assert result["mode"] == "hybrid"
    assert result["eligible_count"] == 0
    assert result["selected"] == []
    assert result["context"] == ""
