from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent import memory
from agent.memory_routes import install_routes


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(memory, "ROOT", root)
    monkeypatch.setattr(memory, "MEMORY_DB", root / "memory.db")
    monkeypatch.setattr(
        memory.memory_embeddings,
        "semantic_scores",
        lambda *_args, **_kwargs: None,
    )
    app = FastAPI()
    install_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_memory_crud(client):
    created = client.post(
        "/api/memory",
        json={"text": "Für Coding nutze ich Qwen3.8-27B.", "pinned": True},
    )
    assert created.status_code == 200
    item = created.json()["memory"]

    listed = client.get("/api/memory")
    assert listed.status_code == 200
    assert listed.json()["memories"][0]["id"] == item["id"]

    updated = client.patch(
        f"/api/memory/{item['id']}",
        json={"importance": 0.95, "category": "coding"},
    )
    assert updated.status_code == 200
    assert updated.json()["memory"]["importance"] == 0.95

    deleted = client.delete(f"/api/memory/{item['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/memory").json()["memories"] == []


def test_memory_observe_and_context_retrieves_once(client):
    observed = client.post(
        "/api/memory/observe",
        json={"message": "Merk dir: Nenn mich Nobby.", "source_chat_id": "chat-1"},
    )
    assert observed.status_code == 200
    assert observed.json()["action"] == "remembered"
    memory_id = observed.json()["memory"]["id"]

    context = client.get(
        "/api/memory/context",
        params={"query": "Wie sollst du mich nennen?"},
    )
    assert context.status_code == 200
    payload = context.json()
    assert payload["memories"]
    assert "Nobby" in payload["context"]
    assert memory.get(memory_id)["use_count"] == 1


def test_memory_embedding_status(client, monkeypatch):
    monkeypatch.setattr(
        memory.memory_embeddings,
        "status",
        lambda _db: {
            "available": True,
            "mode": "hybrid",
            "model": "qwen-test",
            "dimensions": 3,
            "stored_vectors": 2,
        },
    )

    response = client.get("/api/memory/embedding-status")

    assert response.status_code == 200
    assert response.json()["mode"] == "hybrid"
    assert response.json()["model"] == "qwen-test"
