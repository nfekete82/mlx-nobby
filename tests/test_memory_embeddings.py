import hashlib
import sqlite3

import pytest

from agent import memory_embeddings


def _database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "CREATE TABLE memories(id TEXT PRIMARY KEY, text TEXT NOT NULL)"
    )
    memory_embeddings.ensure_schema(connection)
    connection.commit()
    connection.close()


def _seed_memories(database, memories):
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO memories(id, text) VALUES (?, ?)",
            [(item["id"], item["text"]) for item in memories],
        )


def test_semantic_scores_lazy_backfill_and_refresh_stale_text(tmp_path, monkeypatch):
    database = tmp_path / "memory.db"
    _database(database)
    health = {
        "ok": True,
        "model": "embedding-role",
        "upstream_model": "qwen-test",
        "dimensions": 3,
    }
    monkeypatch.setattr(memory_embeddings, "embedding_health", lambda: health)

    embedded_texts = []

    def fake_request(path, payload=None, **_kwargs):
        if path == "/embeddings":
            texts = list(payload["texts"])
            embedded_texts.extend(texts)
            vectors = [
                [1.0, 0.0, 0.0]
                if "Coding" in text
                else [0.0, 1.0, 0.0]
                for text in texts
            ]
            return {
                "model": "embedding-role",
                "upstream_model": "qwen-test",
                "dimensions": 3,
                "vectors": vectors,
            }
        if path == "/embedding":
            return {
                "model": "embedding-role",
                "upstream_model": "qwen-test",
                "dimensions": 3,
                "vectors": [[1.0, 0.0, 0.0]],
            }
        raise AssertionError(path)

    monkeypatch.setattr(memory_embeddings, "_request", fake_request)

    memories = [
        {"id": "coding", "text": "Für Coding nutze ich Qwen3.8."},
        {"id": "image", "text": "Für Bilder nutze ich Qwen Image."},
    ]
    _seed_memories(database, memories)

    first = memory_embeddings.semantic_scores(
        database,
        memories,
        "Welche KI nehme ich zum Programmieren?",
    )

    assert first["coding"] == pytest.approx(1.0)
    assert first["image"] == pytest.approx(0.0)
    assert embedded_texts == [item["text"] for item in memories]

    embedded_texts.clear()
    second = memory_embeddings.semantic_scores(database, memories, "Coding")
    assert second["coding"] == pytest.approx(1.0)
    assert embedded_texts == []

    changed = [
        {"id": "coding", "text": "Für Bilder nutze ich jetzt Qwen Image."},
        memories[1],
    ]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE memories SET text = ? WHERE id = 'coding'",
            (changed[0]["text"],),
        )

    refreshed = memory_embeddings.semantic_scores(database, changed, "Coding")

    assert embedded_texts == [changed[0]["text"]]
    assert refreshed["coding"] == pytest.approx(0.0)

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT model, dimensions, content_hash FROM memory_embeddings WHERE memory_id='coding'"
        ).fetchone()
    assert row[0] == "qwen-test"
    assert row[1] == 3
    assert row[2] == hashlib.sha256(changed[0]["text"].encode()).hexdigest()


def test_semantic_scores_fall_back_when_embedding_service_is_unavailable(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "memory.db"
    _database(database)
    monkeypatch.setattr(memory_embeddings, "embedding_health", lambda: None)

    result = memory_embeddings.semantic_scores(
        database,
        [{"id": "one", "text": "Some memory"}],
        "question",
    )

    assert result is None


def test_status_reports_hybrid_mode_and_vector_count(tmp_path, monkeypatch):
    database = tmp_path / "memory.db"
    _database(database)
    monkeypatch.setattr(
        memory_embeddings,
        "embedding_health",
        lambda: {
            "ok": True,
            "model": "role",
            "upstream_model": "qwen-test",
            "dimensions": 3,
        },
    )

    result = memory_embeddings.status(database)

    assert result["available"] is True
    assert result["mode"] == "hybrid"
    assert result["model"] == "qwen-test"
    assert result["dimensions"] == 3
    assert result["stored_vectors"] == 0
