"""Exercise the gateway against real HTTP SSE, without loading MLX models."""
import asyncio
from contextlib import contextmanager
import http.server
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.openai_gateway import StopFilter, Transfer, TransferResponse, install_routes, combine
from local_security import LocalRequestGuard


def chunk(delta=None, finish=None, usage=None):
    return {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1,
            "model": "/private/model", "choices": [] if usage else [
                {"index": 0, "delta": delta or {}, "finish_reason": finish}], "usage": usage}


@pytest.fixture
def gateway():
    payloads, events = [], []
    frames = [chunk({"role": "assistant", "content": "hello "}),
              chunk({"content": "world"}), chunk(finish="stop"),
              chunk(usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6})]

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            payloads.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if payloads[-1]["messages"][0]["content"] == "stall":
                server.received.set()
                self.rfile.read(1)  # EOF proves the native socket was closed.
                server.disconnected.set()
                return
            self.send_response(200)
            if not payloads[-1].get("stream"):
                body = json.dumps(combine(frames, "mlx-nobby/coding")).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for frame in frames:
                    self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.received, server.disconnected = threading.Event(), threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @contextmanager
    def lease(cancel):
        events.append("lease")
        try:
            yield
        finally:
            events.append("release")

    resolved = {"repo": "/private/model", "available": True}
    def ensure(role):
        events.append(("resolve", role))
        return {"resolved": dict(resolved)}

    host = SimpleNamespace(runtime_coordinator=SimpleNamespace(chat_runtime=lease),
                           MODEL_RUNTIME_LOCK=threading.RLock(), ensure_model_for_role=ensure,
                           resolve_model_role=lambda role: dict(resolved),
                           detect_model_metadata=lambda repo: {"available": True},
                           load_config=lambda: {"PORT": server.server_port})
    app = FastAPI()
    app.add_middleware(LocalRequestGuard)
    install_routes(app, host=host)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield SimpleNamespace(client=client, host=host, frames=frames, payloads=payloads,
                              events=events, resolved=resolved)
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(**options):
    return {"model": "mlx-nobby/coding", "messages": [{"role": "user", "content": "Hi"}], **options}


def test_models_roles_unavailable_and_no_paths(gateway):
    data = gateway.client.get("/v1/models").json()
    assert data["object"] == "list"
    assert {m["id"] for m in data["data"]} == {"mlx-nobby/coding", "mlx-nobby/chat", "mlx-nobby/agent"}
    assert "/private" not in json.dumps(data)
    gateway.resolved["available"] = False
    assert gateway.client.get("/v1/models").json()["data"] == []
    r = gateway.client.post("/v1/chat/completions", json=request())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "model_unavailable"


def test_nonstream_usage_role_and_stateless_contract(gateway):
    messages = [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Again"}]
    r = gateway.client.post("/v1/chat/completions", json=request(messages=messages, max_completion_tokens=12))
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "hello world"
    assert data["usage"]["total_tokens"] == 6
    assert data["model"] == "mlx-nobby/coding"
    assert gateway.payloads[0]["messages"] == messages
    assert gateway.payloads[0]["stream"] is True
    assert gateway.payloads[0]["max_tokens"] == 12
    assert gateway.events[:2] == ["lease", ("resolve", "coding")]
    assert gateway.events[-1] == "release"


@pytest.mark.parametrize("include_usage", [True, False])
def test_streaming_done_usage(gateway, include_usage):
    r = gateway.client.post("/v1/chat/completions", json=request(stream=True, stream_options={"include_usage": include_usage}))
    assert r.headers["content-type"] == "text/event-stream"
    assert r.text.endswith("data: [DONE]\n\n")
    chunks = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")]
    assert len(chunks) >= 3
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert all(c["model"] == "mlx-nobby/coding" for c in chunks)
    assert any(c.get("usage") for c in chunks) == include_usage


@pytest.mark.parametrize("stream", [False, True])
def test_native_tool_deltas_and_continuation(gateway, stream):
    gateway.frames[:] = [chunk({"role": "assistant", "tool_calls": [
        {"index": 0, "id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"hi.txt"}'}}]}),
        chunk(finish="tool_calls")]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    r = gateway.client.post("/v1/chat/completions", json=request(stream=stream, tools=tools, tool_choice="required"))
    assert r.status_code == 200
    assert gateway.payloads[0]["tools"] == tools
    if not stream:
        call = r.json()["choices"][0]["message"]["tool_calls"][0]
        assert call == {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"hi.txt"}'}}
        assert "usage" not in r.json()
    else:
        assert '"index": 0' in r.text and '"finish_reason": "tool_calls"' in r.text
        call = {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"hi.txt"}'}}
    messages = request()["messages"] + [{"role": "assistant", "tool_calls": [call]},
                                          {"role": "tool", "tool_call_id": "call-1", "content": "hello"}]
    assert gateway.client.post("/v1/chat/completions", json=request(messages=messages)).status_code == 200
    assert gateway.payloads[-1]["messages"] == messages


@pytest.mark.parametrize("options", [{"messages": []}, {"messages": [{}]}, {"stream": "true"},
    {"max_tokens": 0}, {"max_tokens": 1, "max_completion_tokens": 1}, {"unsupported": True},
    {"tool_choice": "required"}, {"tool_choice": {"type": "function", "function": {"name": []}}},
    {"messages": [{"role": "tool", "content": "x", "tool_call_id": "missing"}]},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "/private/file"}}]}]},
    {"stop": ""}, {"temperature": float("inf")}])
def test_malformed_requests(gateway, options):
    r = gateway.client.post("/v1/chat/completions", content=json.dumps(request(**options)), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert not gateway.payloads


def test_unknown_alias_auth_security_content_type(gateway):
    for model in ["/private/model", "qwen", "mlx-nobby/image"]:
        assert gateway.client.post("/v1/chat/completions", json=request(model=model)).status_code == 404
    for headers in [{}, {"Authorization": "Bearer placeholder"}]:
        assert gateway.client.post("/v1/chat/completions", json=request(), headers=headers).status_code == 200
    assert gateway.client.post("/v1/chat/completions", content="{}").status_code == 415
    assert gateway.client.post("/v1/chat/completions", content="{", headers={"Content-Type": "application/json"}).status_code == 400
    assert gateway.client.get("/v1/models", headers={"Host": "evil.example"}).status_code == 403
    assert gateway.client.get("/v1/models", headers={"Host": "evil.example"}).json()["error"]["code"] == "local_access_required"
    assert gateway.client.get("/v1/models", headers={"Origin": "https://evil.example"}).status_code == 403


def test_offline_and_stream_exception(gateway):
    gateway.host.load_config = lambda: {"PORT": 1}
    r = gateway.client.post("/v1/chat/completions", json=request())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runtime_unavailable"


def test_stop_crosses_chunk_boundaries_and_flushes():
    stop = StopFilter(["world"])
    assert stop.apply(chunk({"content": "hello wo"}))["choices"][0]["delta"]["content"] == "hello "
    c = stop.apply(chunk({"content": "rld ignored"}))
    assert c["choices"][0]["delta"]["content"] == ""
    assert stop.stopped and c["choices"][0]["finish_reason"] == "stop"
    stop = StopFilter("world")
    stop.apply(chunk({"content": "hello wo"}))
    assert stop.apply(chunk(finish="length"))["choices"][0]["delta"]["content"] == "wo"


@pytest.mark.parametrize("stream", [False, True])
def test_stop_aborts_native_generation_without_fake_usage(gateway, stream):
    r = gateway.client.post("/v1/chat/completions", json=request(stream=stream, stop="world"))
    assert r.status_code == 200
    assert "world" not in r.text
    if not stream:
        assert r.json()["choices"][0]["message"]["content"] == "hello "
        assert "usage" not in r.json()


def test_live_role_change_and_missing_model(gateway):
    gateway.resolved["repo"] = "/changed/model"
    assert gateway.client.post("/v1/chat/completions", json=request()).status_code == 200
    assert gateway.payloads[-1]["model"] == "/changed/model"
    gateway.host.detect_model_metadata = lambda repo: {"available": False}
    assert gateway.client.get("/v1/models").json()["data"] == []
    assert gateway.client.post("/v1/chat/completions", json=request()).status_code == 503


def test_concurrent_requests_use_shared_lock(gateway):
    active = 0
    maximum = 0
    guard = threading.Lock()
    original = gateway.host.ensure_model_for_role
    def ensure(role):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        result = original(role)
        with guard:
            active -= 1
        return result
    gateway.host.ensure_model_for_role = ensure
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: gateway.client.post("/v1/chat/completions", json=request()), range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert len(gateway.payloads) == 8
    assert maximum == 1
    assert gateway.events.count("release") == 8


@pytest.mark.parametrize("stream", [False, True])
def test_web_relay_preserves_protocol(gateway, stream):
    # The native test server doubles as the host here; the relay must not
    # reinterpret or collect the host's SSE into a non-stream response.
    for frame in gateway.frames:
        frame["model"] = "mlx-nobby/coding"
    app = FastAPI()
    install_routes(app, agent_url=f"http://127.0.0.1:{gateway.host.load_config()['PORT']}")
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json=request(stream=stream))
    assert response.status_code == 200
    if stream:
        assert response.text.endswith("data: [DONE]\n\n")
    else:
        assert response.json()["choices"][0]["message"]["content"] == "hello world"


def test_disconnect_unblocks_real_native_socket(gateway):
    port = gateway.host.load_config()["PORT"]
    def worker(transfer):
        from backend.openai_gateway import runtime_session
        with runtime_session(gateway.host, transfer, "coding"):
            transfer.open(f"http://127.0.0.1:{port}/v1/chat/completions", request(messages=[{"role": "user", "content": "stall"}]))
    async def run():
        transfer = Transfer(worker)
        async def receive():
            await asyncio.sleep(0.1)
            return {"type": "http.disconnect"}
        async def send(message):
            pass
        await TransferResponse(transfer, False)({"type": "http"}, receive, send)
        await asyncio.to_thread(transfer.thread.join, 2)
        assert not transfer.thread.is_alive()
    asyncio.run(run())
    assert gateway.events[-1] == "release"


def test_cancellation_while_waiting_for_shared_model_lock(gateway):
    from backend.openai_gateway import runtime_session
    def worker(transfer):
        with runtime_session(gateway.host, transfer, "coding"):
            pytest.fail("Cancelled queued requests must not resolve or call a model")
    async def run():
        transfer = Transfer(worker)
        async def receive():
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}
        async def send(message):
            pass
        await TransferResponse(transfer, True)({"type": "http"}, receive, send)
        await asyncio.to_thread(transfer.thread.join, 2)
        assert not transfer.thread.is_alive()
    with gateway.host.MODEL_RUNTIME_LOCK:
        asyncio.run(run())
    assert gateway.events == ["lease", "release"]


def test_simultaneous_disconnect_and_sender_cancellation():
    async def run():
        transfer = Transfer(lambda state: state.cancel.wait(1))
        async def receive():
            # No yield: listener and sender both finish before wait resumes.
            return {"type": "http.disconnect"}
        async def send(message):
            pytest.fail("A disconnected client must not receive a response")
        await TransferResponse(transfer, True)({"type": "http"}, receive, send)
        await asyncio.to_thread(transfer.thread.join, 2)
        assert not transfer.thread.is_alive()
    asyncio.run(run())


def test_memory_middleware_never_enriches_external_requests(gateway, monkeypatch):
    from agent.memory_middleware import MemoryChatMiddleware
    from agent import memory_lifecycle
    calls = []
    monkeypatch.setattr(memory_lifecycle, "enrich_messages", lambda *a, **kw: calls.append(a))
    app = FastAPI()
    install_routes(app, host=gateway.host)
    app.add_middleware(MemoryChatMiddleware)
    with TestClient(app) as client:
        assert client.post("/v1/chat/completions", json=request()).status_code == 200
    assert calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_upstream_error_during_stream(gateway, stream):
    gateway.frames[:] = [{"error": "private runtime detail"}]
    result = gateway.client.post("/v1/chat/completions", json=request(stream=stream))
    if stream:
        assert '"error"' in result.text and result.text.endswith("data: [DONE]\n\n")
    else:
        assert result.status_code == 503 and "error" in result.json()
    assert "private runtime detail" not in result.text


@pytest.mark.parametrize("phase", ["queue", "headers", "body"])
def test_disconnect_cancels_worker_and_releases_runtime(gateway, phase):
    acquired = threading.Event()
    released = threading.Event()

    def worker(transfer):
        from backend.openai_gateway import runtime_session
        with runtime_session(gateway.host, transfer, "coding"):
            acquired.set()
            if phase != "queue":
                transfer.put(("headers", None))
            if phase == "body":
                transfer.put(("body", b"data: {}\n\n"))
            transfer.cancel.wait(2)
        released.set()

    async def run():
        transfer = Transfer(worker)
        async def receive():
            while not acquired.is_set():
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.03)
            return {"type": "http.disconnect"}
        async def send(message):
            pass
        await TransferResponse(transfer, True)({"type": "http"}, receive, send)
        await asyncio.to_thread(transfer.thread.join, 2)
        assert transfer.cancel.is_set()
        assert not transfer.thread.is_alive()
    asyncio.run(run())
    assert released.is_set()
    assert gateway.events[-1] == "release"
