import asyncio
import json
import threading
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


@pytest.mark.parametrize("vision", [False, True])
def test_media_wait_does_not_trigger_agent_recovery(monkeypatch, vision):
    monkeypatch.setattr(web_routes, "FIRST_BYTE_TIMEOUT", 0.01)
    monkeypatch.setattr(web_routes, "MEDIA_WAIT_TIMEOUT", 0.10)
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 0.01)

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

    request = (
        _vision_request() if vision else
        web_routes.ReliableChatRequest(messages=[{"role": "user", "content": "Hi"}])
    )
    body = asyncio.run(_collect(web_routes._reliable_stream(
        request,
        stream_factory=factory,
        agent_url="http://agent",
    )))

    assert b"After media" in body
    assert factory.calls == 1


def _vision_request():
    return web_routes.ReliableChatRequest(messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
        ],
    }])


def _watchdog_setup(monkeypatch):
    monkeypatch.setattr(web_routes, "FIRST_BYTE_TIMEOUT", 0.02)
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 0.20)
    monkeypatch.setattr(web_routes, "STREAM_STALL_TIMEOUT", 0.03)
    monkeypatch.setattr(web_routes, "VISION_HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr(web_routes, "_agent_diagnostics", lambda url: {
        "status": "ok", "agent_pid": 10,
        "lease": {"active_workload": "chat"},
        "runtime": {"online": True},
    })
    recoveries = []
    monkeypatch.setattr(web_routes, "_request_recovery", lambda url, reason: (
        recoveries.append(reason) or {"scheduled": True}
    ))
    monkeypatch.setattr(web_routes, "_agent_ready_with_new_pid", lambda *args: True)
    return recoveries


@pytest.mark.parametrize("metadata", [False, True])
def test_long_vision_prefill_sends_heartbeats_without_recovery(monkeypatch, metadata):
    recoveries = _watchdog_setup(monkeypatch)

    async def prefill():
        if metadata:
            yield b'event: sources\ndata: {"sources":[]}\n\n'
        await asyncio.sleep(0.08)  # Beyond both text first-byte and stall limits.
        yield b'data: {"type":"content","text":"An image"}\n\n'
        yield b'event: done\ndata: {}\n\n'

    factory = _StreamFactory([prefill])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        _vision_request(), stream_factory=factory, agent_url="http://agent",
    )))
    assert body.startswith(web_routes.VISION_HEARTBEAT)
    assert body.count(web_routes.VISION_HEARTBEAT) >= 2
    assert body.count(b'"text":"An image"') == 1
    assert b'event: error' not in body
    assert factory.calls == 1
    assert recoveries == []


def test_text_timeout_unchanged_with_vision_budget(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)

    async def slow():
        await asyncio.sleep(0.08)
        yield b'data: {"type":"content","text":"Too late"}\n\n'

    async def fast():
        yield b'data: {"type":"content","text":"Retry"}\n\n'

    factory = _StreamFactory([slow, fast])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        web_routes.ReliableChatRequest(messages=[{"role": "user", "content": "Hi"}]),
        stream_factory=factory, agent_url="http://agent",
    )))
    assert body == b'data: {"type":"content","text":"Retry"}\n\n'
    assert factory.calls == 2
    assert recoveries == ["chat_first_byte_timeout"]


def test_dead_vision_runtime_recovers_once_despite_heartbeats(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 0.05)
    closed = []

    async def dead():
        try:
            await asyncio.sleep(5)
            yield b"never"
        finally:
            closed.append(True)

    factory = _StreamFactory([dead])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        _vision_request(), stream_factory=factory, agent_url="http://agent",
    )))
    assert body.count(web_routes.VISION_HEARTBEAT) >= 2
    assert b'"code": "stream_stalled"' in body
    assert factory.calls == 2
    assert recoveries == ["chat_first_byte_timeout"]
    assert len(closed) == 2


def test_vision_metadata_cannot_extend_absolute_prefill_deadline(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 0.05)
    closed = []

    async def metadata_only():
        try:
            while True:
                yield b'event: metrics\ndata: {}\n\n'
                await asyncio.sleep(0.005)
        finally:
            closed.append(True)

    factory = _StreamFactory([metadata_only])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        _vision_request(), stream_factory=factory, agent_url="http://agent",
    )))
    assert b'event: error' in body
    assert recoveries == ["chat_first_byte_timeout"]
    assert closed == [True]


def test_vision_after_output_uses_normal_stall_deadline(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)

    async def stalls_after_output():
        yield b'data: {"type":"content","text":"First"}\n\n'
        await asyncio.sleep(5)
        yield b"never"

    factory = _StreamFactory([stalls_after_output])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        _vision_request(), stream_factory=factory, agent_url="http://agent",
    )))
    assert b'"code": "stream_stalled_after_output"' in body
    assert recoveries == ["chat_stream_stalled_after_output"]
    assert factory.calls == 1


def test_vision_factory_does_not_block_heartbeat_or_watchdog(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)
    # This test verifies coordination, not expiry of the artificial 200ms budget.
    # Dedicated tests above retain the short absolute-prefill/stall deadlines.
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 1.0)
    factory_entered = threading.Event()
    release_factory = threading.Event()
    event_loop_thread = threading.get_ident()
    closed = []

    async def answer():
        try:
            yield b'data: {"type":"content","text":"Image"}\n\n'
        finally:
            closed.append(True)

    factory = _StreamFactory([answer])

    def slow_factory(request):
        assert threading.get_ident() != event_loop_thread
        factory_entered.set()
        assert release_factory.wait(timeout=5), "Test did not release the factory"
        return factory(request)

    async def drive():
        stream = web_routes._reliable_stream(
            _vision_request(), stream_factory=slow_factory, agent_url="http://agent",
        )
        try:
            assert await anext(stream) == web_routes.VISION_HEARTBEAT
            # The initial heartbeat precedes worker dispatch. Drive the real stream
            # until entry, then require another heartbeat while the worker is held.
            while not factory_entered.is_set():
                assert await anext(stream) == web_routes.VISION_HEARTBEAT
            assert await anext(stream) == web_routes.VISION_HEARTBEAT
            assert not release_factory.is_set()
            assert factory.calls == 0
            assert closed == []
            assert recoveries == []

            release_factory.set()
            return await _collect(stream)
        finally:
            release_factory.set()  # Also unblock executor shutdown on assertion failure.
            await stream.aclose()

    body = asyncio.run(drive())
    assert b'"text":"Image"' in body
    assert b'event: error' not in body
    assert factory.calls == 1
    assert closed == [True]
    assert recoveries == []


def test_vision_disconnect_cancels_pending_read(monkeypatch):
    _watchdog_setup(monkeypatch)
    closed = []

    async def dead():
        try:
            await asyncio.sleep(5)
            yield b"never"
        finally:
            closed.append(True)

    async def disconnect():
        stream = web_routes._reliable_stream(
            _vision_request(), stream_factory=_StreamFactory([dead]), agent_url="http://agent",
        )
        assert await anext(stream) == web_routes.VISION_HEARTBEAT
        assert await anext(stream) == web_routes.VISION_HEARTBEAT
        await stream.aclose()

    asyncio.run(disconnect())
    assert closed == [True]


@pytest.mark.parametrize("image", ["https://example.test/image.png", {"url": "data:image/png;base64,AA=="}])
def test_vision_detection_includes_image_history(image):
    request = web_routes.ReliableChatRequest(messages=[
        {"role": "user", "content": [{"type": "image_url", "image_url": image}]},
        {"role": "assistant", "content": "A photo"},
        {"role": "user", "content": "Explain more"},
    ])
    assert web_routes._has_vision_input(request)


def test_dead_vision_runtime_retry_returns_answer(monkeypatch):
    recoveries = _watchdog_setup(monkeypatch)
    monkeypatch.setattr(web_routes, "VISION_FIRST_BYTE_TIMEOUT", 0.05)

    async def dead():
        await asyncio.sleep(5)
        yield b"never"

    async def recovered():
        yield b'data: {"type":"content","text":"Vision recovered"}\n\n'

    factory = _StreamFactory([dead, recovered])
    body = asyncio.run(_collect(web_routes._reliable_stream(
        _vision_request(), stream_factory=factory, agent_url="http://agent",
    )))
    assert b'Vision recovered' in body
    assert b'event: error' not in body
    assert factory.calls == 2
    assert recoveries == ["chat_first_byte_timeout"]
