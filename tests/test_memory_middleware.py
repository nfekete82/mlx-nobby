import json
import threading
import time

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from agent import memory
from agent import memory_lifecycle
from agent import memory_middleware
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


def test_slow_memory_enrichment_fails_open_without_blocking_chat(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_enrichment(messages, **_kwargs):
        started.set()
        release.wait(timeout=1.0)
        return [
            {"role": "system", "content": "late memory"},
            *messages,
        ]

    monkeypatch.setattr(
        memory_lifecycle,
        "enrich_messages",
        slow_enrichment,
    )
    monkeypatch.setattr(
        memory_middleware,
        "MEMORY_ENRICH_TIMEOUT_SECONDS",
        0.02,
    )

    payload = {
        "messages": [
            {"role": "user", "content": "Warum antwortest du nicht?"}
        ]
    }

    before = time.monotonic()
    try:
        response = client.post("/api/runtime/chat/stream", json=payload)
        elapsed = time.monotonic() - before

        assert started.wait(timeout=0.2)
        assert response.status_code == 200
        assert response.json()["messages"] == payload["messages"]
        assert elapsed < 0.3
    finally:
        release.set()


def test_unrelated_routes_are_untouched(client):
    payload = {"messages": [{"role": "user", "content": "Merk dir: geheim"}]}

    response = client.post("/unrelated", content=json.dumps(payload))

    assert response.status_code == 200
    assert response.json() == payload
    assert memory.list_memories() == []
