import asyncio
import json
import threading
import time
import urllib.error

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from agent import memory
from agent import memory_lifecycle
from agent import memory_middleware
from agent import memory_dashboard
from agent import personal_memory as pm
from agent import chat_archive, memory_embeddings
from agent.memory_middleware import MemoryChatMiddleware


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = tmp_path / "mlx-web"
    monkeypatch.setattr(memory, "ROOT", root)
    monkeypatch.setattr(memory, "MEMORY_DB", root / "memory.db")
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "private.sqlite3")
    monkeypatch.setattr(chat_archive, "DB_PATH", root / "archive.sqlite3")
    monkeypatch.setattr(memory_dashboard, "STATE_PATH", tmp_path / "pause.json")
    monkeypatch.setattr(memory_embeddings, '_health_cache', {'expires':0.0,'value':None})
    def offline(*_args, **_kwargs):
        raise urllib.error.URLError('Isolated test: no embedding service')
    monkeypatch.setattr(memory_embeddings, '_request', offline)

    app = FastAPI()
    app.add_middleware(MemoryChatMiddleware)

    @app.post("/api/runtime/chat/stream")
    async def chat(request: Request):
        payload = await request.json()

        if request.query_params.get("mode") == "stream":
            async def events():
                yield b"data: first\n\n"
                await asyncio.sleep(0)
                yield b"data: second\n\n"

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
            )

        return payload

    @app.post("/unrelated")
    async def unrelated(request: Request):
        return await request.json()

    with TestClient(app, base_url="http://localhost") as client:
        yield client
    # wait_for(shield(...)) deliberately leaves retrieval running. Drain it
    # BEFORE monkeypatch restores paths and functions for the next test.
    middleware = app.middleware_stack
    while not isinstance(middleware, MemoryChatMiddleware):
        middleware = middleware.app
    for executor in (middleware._memory_executor, middleware._private_executor,
                     middleware._overview_executor):
        executor.shutdown(wait=True, cancel_futures=True)


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


@pytest.mark.parametrize('cached_health', [False, True], ids=['cold-health','warm-health'])
def test_embedding_deadline_preserves_pinned_legacy_memory(client, monkeypatch, cached_health):
    pinned = memory.add('Nenn mich Nobby.', pinned=True)
    memory.add('Für Bildgenerierung verwende ich Beispielmodell.', pinned=True)
    memory.add('Antworte kurz.', category='communication', pinned=True)
    entered, release = threading.Event(), threading.Event()
    requests = []
    if cached_health:
        memory_embeddings._health_cache.update(expires=time.monotonic()+60, value={
            'ok':True,'model':'isolated-test','dimensions':3,
        })
    def blocked(path, *_args, **_kwargs):
        requests.append(path)
        entered.set()
        release.wait(timeout=5)
        raise urllib.error.URLError('Isolated blocked embedding service')
    monkeypatch.setattr(memory_embeddings, '_request', blocked)
    monkeypatch.setattr(memory_middleware, 'MEMORY_ENRICH_TIMEOUT_SECONDS', .01)
    try:
        for query in ('Erkläre Docker.', 'Erkläre CSS.'):
            response = client.post('/api/runtime/chat/stream', json={
                'messages':[{'role':'user','content':query}],
            })
            assert entered.is_set() and not release.is_set()
            assert response.status_code == 200
            context = '\n'.join(m['content'] for m in response.json()['messages'] if m['role']=='system')
            assert 'Nenn mich Nobby.' in context
            assert 'Antworte kurz.' in context
            assert 'Beispielmodell' not in context
            assert response.json()['messages'][-1]['content'] == query
        assert requests == (['/embeddings'] if cached_health else ['/health'])
        assert memory.get(pinned['id'])['use_count'] == 0
    finally:
        release.set()


def test_streaming_chat_observes_explicit_remember(client):
    pm.set_enabled(True)
    response = client.post(
        "/api/runtime/chat/stream",
        json={
            "chat_id": "synthetic-chat",
            "messages": [
                {
                    "role": "user",
                    "content": "Merk dir: Für Coding nutze ich Qwen3.8-27B.",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert '"persisted": true' in response.text
    items = pm.list_facts()
    assert len(items) == 1
    assert "Qwen3.8-27B" in items[0]["value"]


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




def test_slow_semantic_recall_does_not_inject_unrelated_private_identity(client, monkeypatch):
    pm.set_enabled(True)
    pm.create_fact("ich", "beruf", "Informatiker", sensitive=True)
    pm.create_fact("partner", "gesundheit", "Beispieldiagnose", sensitive=True)
    started, release = threading.Event(), threading.Event()

    def slow_enrichment(messages, **_kwargs):
        started.set()
        release.wait(timeout=1.0)
        return messages

    monkeypatch.setattr(memory_lifecycle, "enrich_messages", slow_enrichment)
    monkeypatch.setattr(memory_middleware, "MEMORY_ENRICH_TIMEOUT_SECONDS", 0.01)
    try:
        response = client.post("/api/runtime/chat/stream", json={
            "messages": [{"role": "user", "content": "Erkläre CSS."}]
        })
        assert started.wait(timeout=0.2)
        assert response.status_code == 200
        assert response.json()["messages"] == [{"role": "user", "content": "Erkläre CSS."}]
    finally:
        release.set()

def test_memory_middleware_preserves_streaming_response(client):
    response = client.post(
        "/api/runtime/chat/stream?mode=stream",
        json={"messages": [{"role": "user", "content": "Hallo"}]},
    )

    assert response.status_code == 200
    assert response.text == "data: first\n\ndata: second\n\n"


def test_unrelated_routes_are_untouched(client):
    payload = {"messages": [{"role": "user", "content": "Merk dir: geheim"}]}

    response = client.post("/unrelated", content=json.dumps(payload))

    assert response.status_code == 200
    assert response.json() == payload
    assert memory.list_memories() == []


def test_chat_identity_reaches_memory_clarification(client, monkeypatch):
    seen = []

    def enrich(messages, **kwargs):
        seen.append(kwargs.get('source_chat_id'))
        return messages

    monkeypatch.setattr(memory_lifecycle, 'enrich_messages', enrich)
    response = client.post('/api/runtime/chat/stream', json={
        'chat_id': 'synthetic-question-chat',
        'messages': [{'role': 'user', 'content': 'Ja, das neue Datum stimmt'}],
    })
    assert response.status_code == 200
    assert seen == ['synthetic-question-chat']


def test_rejected_origin_cannot_observe_or_resolve_memory_before_local_guard(monkeypatch):
    from local_security import LocalRequestGuard
    observed = []

    def enrich(messages, **kwargs):
        observed.append(messages)
        return messages

    monkeypatch.setattr(memory_lifecycle, 'enrich_messages', enrich)
    app = FastAPI()
    app.add_middleware(LocalRequestGuard)
    # Production installs the memory layer after the original app guard.
    app.add_middleware(MemoryChatMiddleware)

    @app.post('/api/runtime/chat/stream')
    async def echo(request: Request):
        return await request.json()

    with TestClient(app, base_url='http://localhost') as client:
        response = client.post('/api/runtime/chat/stream', headers={
            'Origin': 'https://foreign.invalid', 'Sec-Fetch-Site': 'cross-site',
        }, json={'chat_id': 'synthetic', 'messages': [
            {'role': 'user', 'content': 'Ja, das neue Datum stimmt'},
        ]})
    assert response.status_code == 403
    assert observed == [], 'Rejected requests must not reach memory enrichment'


def test_explicit_overview_uses_real_facts_and_skips_slow_legacy_recall(client, monkeypatch):
    """A user asking what the model knows gets stored facts, not generic text."""
    pm.set_enabled(True)
    pm.create_fact("ich", "beruf", "Informatiker", sensitive=True)
    pm.create_fact("familie.sohn", "name", "Beispielkind", sensitive=True)
    pm.create_fact("projekte.sandforge", "ziel", "Verbesserte Spiel-KI", sensitive=True)

    def expensive_legacy(*_args, **_kwargs):
        raise AssertionError("Explicit overview must not enter legacy embedding path")

    monkeypatch.setattr(memory_lifecycle, "enrich_messages", expensive_legacy)
    response = client.post("/api/runtime/chat/stream", json={
        "chat_id": "fictional-overview",
        "messages": [{"role": "user", "content": "Was weißt du alles über mich?"}],
    })
    assert response.status_code == 200
    messages = response.json()["messages"]
    context = "\\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    assert "Informatiker" in context
    assert "Beispielkind" in context
    assert "Verbesserte Spiel-KI" in context
    assert messages[-1]["content"] == "Was weißt du alles über mich?"


def test_explicit_specific_recall_injects_personal_fact_when_index_is_empty(
    client, monkeypatch,
):
    """Actual streaming middleware must use the direct fact-store fallback."""
    from agent import knowledge_memory

    pm.set_enabled(True)
    pm.create_fact("familie.sohn", "name", "Milan", sensitive=True)
    pm.create_fact("partner", "gesundheit", "Privater Testfall", sensitive=True)
    monkeypatch.setattr(knowledge_memory, "context", lambda *_a, **_kw: "")

    messages = [{"role": "user", "content": "Wie heißt mein Sohn?"}]
    response = client.post("/api/runtime/chat/stream", json={
        "chat_id": "synthetic-memory-question", "messages": messages,
    })

    assert response.status_code == 200
    enriched = response.json()["messages"]
    context = "\n".join(x.get("content", "") for x in enriched if x.get("role") == "system")
    assert "PRIVATE PERSONAL MEMORY" in context
    assert "Milan" in context
    assert "Privater Testfall" not in context
    assert enriched[-1] == messages[-1]


def test_non_overview_uses_normal_enrichment_route(client, monkeypatch):
    calls = []
    def regular(messages, **kwargs):
        calls.append(kwargs)
        return [{"role": "system", "content": "REGULAR_CONTEXT"}, *messages]
    monkeypatch.setattr(memory_lifecycle, "enrich_messages", regular)
    response = client.post("/api/runtime/chat/stream", json={
        "messages": [{"role": "user", "content": "Wie schreibe ich einen CSS-Selektor?"}],
    })
    assert response.status_code == 200
    assert calls
    assert response.json()["messages"][0]["content"] == "REGULAR_CONTEXT"
