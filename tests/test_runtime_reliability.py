import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from agent import runtime_reliability_routes as agent_routes
from backend import chat_reliability_routes as web_routes


def test_runtime_diagnostics_reports_active_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_routes, "STATE_DIR", tmp_path / "leases")
    monkeypatch.setattr(agent_routes, "RECOVERY_STATE_FILE", tmp_path / "recovery.json")
    monkeypatch.setattr(agent_routes, "_pid_alive", lambda pid: True)
    agent_routes.STATE_DIR.mkdir()
    now = time.time()
    (agent_routes.STATE_DIR / "123-7.json").write_text(
        json.dumps({
            "pid": 123,
            "thread": 7,
            "workload": "chat",
            "state": "active",
            "updated_at": now - 4.5,
        }),
        encoding="utf-8",
    )

    data = agent_routes.diagnostics(lambda: {
        "online": True,
        "model": "/Models/Qwen",
        "port": 8000,
        "pid": 999,
        "memory_mb": 12000,
    })

    assert data["status"] == "ok"
    assert data["runtime"]["online"] is True
    assert data["lease"]["active_workload"] == "chat"
    assert data["lease"]["active_age_seconds"] >= 4
    assert data["lease"]["waiting_count"] == 0


def test_recovery_never_interrupts_active_media(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_routes, "STATE_DIR", tmp_path / "leases")
    monkeypatch.setattr(agent_routes, "RECOVERY_STATE_FILE", tmp_path / "recovery.json")
    monkeypatch.setattr(agent_routes, "_pid_alive", lambda pid: True)
    agent_routes.STATE_DIR.mkdir()
    (agent_routes.STATE_DIR / "123-7.json").write_text(
        json.dumps({
            "pid": 123,
            "thread": 7,
            "workload": "video",
            "state": "active",
            "updated_at": time.time() - 60,
        }),
        encoding="utf-8",
    )
    scheduled = []

    with pytest.raises(Exception) as exc_info:
        agent_routes.request_recovery(
            agent_routes.RuntimeRecoveryRequest(reason="chat_stalled"),
            status_provider=lambda: {"online": True},
            restart_scheduler=lambda delay: scheduled.append(delay),
        )

    assert getattr(exc_info.value, "status_code", None) == 409
    assert scheduled == []


def test_stale_chat_recovery_is_scheduled_once_with_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_routes, "STATE_DIR", tmp_path / "leases")
    monkeypatch.setattr(agent_routes, "RECOVERY_STATE_FILE", tmp_path / "recovery.json")
    monkeypatch.setattr(agent_routes, "RECOVERY_MIN_CHAT_AGE_SECONDS", 5.0)
    monkeypatch.setattr(agent_routes, "RECOVERY_COOLDOWN_SECONDS", 60.0)
    monkeypatch.setattr(agent_routes, "_pid_alive", lambda pid: True)
    agent_routes.STATE_DIR.mkdir()
    (agent_routes.STATE_DIR / "123-7.json").write_text(
        json.dumps({
            "pid": 123,
            "thread": 7,
            "workload": "chat",
            "state": "active",
            "updated_at": time.time() - 30,
        }),
        encoding="utf-8",
    )
    scheduled = []

    result = agent_routes.request_recovery(
        agent_routes.RuntimeRecoveryRequest(reason="chat_first_byte_timeout"),
        status_provider=lambda: {"online": True},
        restart_scheduler=lambda delay: scheduled.append(delay),
    )

    assert result["scheduled"] is True
    assert len(scheduled) == 1

    with pytest.raises(Exception) as exc_info:
        agent_routes.request_recovery(
            agent_routes.RuntimeRecoveryRequest(reason="again"),
            status_provider=lambda: {"online": True},
            restart_scheduler=lambda delay: scheduled.append(delay),
        )

    assert getattr(exc_info.value, "status_code", None) == 429
    assert len(scheduled) == 1


def test_runtime_reliability_routes_are_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_routes, "STATE_DIR", tmp_path / "leases")
    monkeypatch.setattr(agent_routes, "RECOVERY_STATE_FILE", tmp_path / "recovery.json")
    app = FastAPI()
    agent_routes.install_routes(
        app,
        status_provider=lambda: {"online": True, "model": "test"},
        restart_scheduler=lambda delay: None,
    )
    count = len(app.routes)
    agent_routes.install_routes(
        app,
        status_provider=lambda: {"online": True},
        restart_scheduler=lambda delay: None,
    )
    assert len(app.routes) == count

    response = TestClient(app).get("/api/runtime/reliability")
    assert response.status_code == 200
    assert response.json()["runtime"]["online"] is True


class _StreamFactory:
    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = 0

    def __call__(self, request):
        index = min(self.calls, len(self.streams) - 1)
        generator_factory = self.streams[index]
        self.calls += 1
        return StreamingResponse(generator_factory(), media_type="text/event-stream")


async def _collect(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
        for chunk in chunks
    )


def test_reliable_stream_passes_through_fast_response(monkeypatch):
    async def immediate():
        yield b'data: {"type":"content","text":"Hi"}\n\n'
        yield b'data: {}\n\n'

    factory = _StreamFactory([immediate])
    request = web_routes.ReliableChatRequest(messages=[{"role": "user", "content": "Hi"}])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        request,
        stream_factory=factory,
        agent_url="http://agent",
    )))

    assert b'"text":"Hi"' in body
    assert factory.calls == 1


def test_zero_byte_stall_recovers_and_retries_once(monkeypatch):
    monkeypatch.setattr(web_routes, "FIRST_BYTE_TIMEOUT", 0.01)
    monkeypatch.setattr(web_routes, "RECOVERY_READY_TIMEOUT", 0.01)

    async def stalled():
        await asyncio.sleep(5)
        yield b"never"

    async def recovered():
        yield b'data: {"type":"content","text":"Recovered"}\n\n'

    factory = _StreamFactory([stalled, recovered])
    monkeypatch.setattr(web_routes, "_agent_diagnostics", lambda url: {
        "status": "ok",
        "agent_pid": 10,
        "lease": {
            "active_workload": "chat",
            "active_age_seconds": 40,
            "waiting_count": 0,
        },
        "runtime": {"online": True},
    })
    recoveries = []
    monkeypatch.setattr(web_routes, "_request_recovery", lambda url, reason: (
        recoveries.append(reason) or {"scheduled": True}
    ))
    monkeypatch.setattr(web_routes, "_agent_ready_with_new_pid", lambda *args: True)

    request = web_routes.ReliableChatRequest(messages=[{"role": "user", "content": "Hi"}])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        request,
        stream_factory=factory,
        agent_url="http://agent",
    )))

    assert b"Recovered" in body
    assert factory.calls == 2
    assert recoveries == ["chat_first_byte_timeout"]


def test_media_wait_does_not_trigger_agent_recovery(monkeypatch):
    monkeypatch.setattr(web_routes, "FIRST_BYTE_TIMEOUT", 0.01)
    monkeypatch.setattr(web_routes, "MEDIA_WAIT_TIMEOUT", 0.10)

    async def delayed_for_media():
        await asyncio.sleep(0.03)
        yield b'data: {"type":"content","text":"After media"}\n\n'

    factory = _StreamFactory([delayed_for_media])
    monkeypatch.setattr(web_routes, "_agent_diagnostics", lambda url: {
        "status": "ok",
        "agent_pid": 10,
        "lease": {"active_workload": "video", "active_age_seconds": 5},
        "runtime": {"online": True},
    })
    monkeypatch.setattr(
        web_routes,
        "_request_recovery",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not recover media")),
    )

    request = web_routes.ReliableChatRequest(messages=[{"role": "user", "content": "Hi"}])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        request,
        stream_factory=factory,
        agent_url="http://agent",
    )))

    assert b"After media" in body
    assert factory.calls == 1
