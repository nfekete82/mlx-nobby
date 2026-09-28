import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from agent import memory
from agent.memory_middleware import MemoryChatMiddleware


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(memory, "ROOT", root)
    monkeypatch.setattr(memory, "MEMORY_DB", root / "memory.db")

    app = FastAPI()
    app.add_middleware(MemoryChatMiddleware)

    @app.post("/api/runtime/chat/stream")
    async def chat(request: Request):
        return await request.json()

    @app.post("/unrelated")
    async def unrelated(request: Request):
        return await request.json()

    return TestClient(app)


def test_streaming_chat_is_enriched(client):
    memory.add("Nenn mich Nobby.", pinned=True)

    response = client.post(
        "/api/runtime/chat/stream",
        json={"messages": [{"role": "user", "content": "Erkläre Docker."}]},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert any(
        message.get("role") == "system"
        and "Nenn mich Nobby." in message.get("content", "")
        for message in messages
    )


def test_streaming_chat_observes_explicit_remember(client):
    response = client.post(
        "/api/runtime/chat/stream",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Merk dir: Für Coding nutze ich Qwen3.8-27B.",
                }
            ]
        },
    )

    assert response.status_code == 200
    items = memory.list_memories()
    assert len(items) == 1
    assert "Qwen3.8-27B" in items[0]["text"]


def test_unrelated_routes_are_untouched(client):
    payload = {"messages": [{"role": "user", "content": "Merk dir: geheim"}]}

    response = client.post("/unrelated", content=json.dumps(payload))

    assert response.status_code == 200
    assert response.json() == payload
    assert memory.list_memories() == []
