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
    app = FastAPI()
    install_routes(app)
    return TestClient(app)


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


def test_memory_observe_and_context(client):
    observed = client.post(
        "/api/memory/observe",
        json={"message": "Merk dir: Nenn mich Nobby.", "source_chat_id": "chat-1"},
    )
    assert observed.status_code == 200
    assert observed.json()["action"] == "remembered"

    context = client.get(
        "/api/memory/context",
        params={"query": "Wie sollst du mich nennen?"},
    )
    assert context.status_code == 200
    payload = context.json()
    assert payload["memories"]
    assert "Nobby" in payload["context"]
