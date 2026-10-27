"""Slow upload processing must leave the web event loop responsive."""

import asyncio
from io import BytesIO
import threading
from types import SimpleNamespace

import httpx
import pytest
import anyio.to_thread
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response

from backend import app as web


@pytest.mark.parametrize("kind", ["pdf", "pdf-index", "audio"])
def test_health_responds_while_upload_worker_is_blocked(monkeypatch, kind):
    entered = threading.Event()
    released = threading.Event()

    def blocking_work():
        entered.set()
        assert released.wait(3), "Upload worker was not released"

    if kind in {"pdf", "pdf-index"}:
        def reader(_data):
            if kind == "pdf":
                blocking_work()
            return SimpleNamespace(is_encrypted=False, pages=[])

        def index(*args, **kwargs):
            if kind == "pdf-index":
                blocking_work()
            return {"status": "queued"}

        monkeypatch.setattr(web, "PdfReader", reader)
        monkeypatch.setattr(web, "agent_json_request", index)
        path, filename, expected = "/api/mlx/documents/parse", "test.pdf", "document_id"
    else:
        def upstream(*args, **kwargs):
            blocking_work()
            response = BytesIO(b'{"text":"test transcription"}')
            response.status = 200
            return response

        monkeypatch.setattr(web.urllib.request, "urlopen", upstream)
        path, filename, expected = "/api/mlx/audio/transcriptions", "test.wav", "text"

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web.app), base_url="http://localhost"
        ) as client:
            task = asyncio.create_task(client.post(path, files={"file": (filename, b"fixture")}))
            try:
                async with asyncio.timeout(1):
                    while not entered.is_set():
                        await asyncio.sleep(0.005)
                    health = await client.get("/api/health")
                assert health.status_code == 200
                assert not task.done(), "Upload should still be waiting in its worker"
            finally:
                released.set()
                response = await task
            assert response.status_code == 200
            assert expected in response.json()

    asyncio.run(scenario())


@pytest.mark.parametrize("shared_pool", [True, False])
def test_upload_saturation_reserves_api_workers_and_defers_queued_reads(monkeypatch, shared_pool):
    """Reproduce the previous shared-pool starvation, then verify isolation."""
    release = threading.Event()
    lock = threading.Lock()
    entered = 0
    reads = 0
    original_read = web.read_upload

    async def counted_read(*args):
        nonlocal reads
        reads += 1
        return await original_read(*args)

    def slow_transcription(*args):
        nonlocal entered
        with lock:
            entered += 1
        assert release.wait(3)
        return Response(b'{"text":"fixture"}', media_type="application/json")

    monkeypatch.setattr(web, "read_upload", counted_read)
    monkeypatch.setattr(web, "_speech_transcription_sync", slow_transcription)
    if shared_pool:
        monkeypatch.setattr(web, "run_upload_work", run_in_threadpool)

    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 2
        tasks = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=web.app), base_url="http://localhost"
            ) as client:
                for _ in range(6):
                    tasks.append(asyncio.create_task(client.post(
                        "/api/mlx/audio/transcriptions",
                        files={"file": ("fixture.wav", b"x" * 65536)},
                    )))
                async with asyncio.timeout(1):
                    while entered < 2:
                        await asyncio.sleep(0.005)
                assert reads == 2, "Queued uploads must remain spooled until admitted"
                if shared_pool:
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(client.get("/api/health"), 0.1)
                else:
                    response = await asyncio.wait_for(client.get("/api/health"), 0.5)
                    assert response.status_code == 200
                # A queued cancellation must neither start a worker nor leak a slot.
                tasks[-1].cancel()
                with pytest.raises(asyncio.CancelledError):
                    await tasks.pop()
                assert entered == 2
                release.set()
                responses = await asyncio.gather(*tasks)
                assert all(response.status_code == 200 for response in responses)
                assert entered == reads == 5
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            limiter.total_tokens = previous

    asyncio.run(scenario())
