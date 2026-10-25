"""Opt-in native vision SSE relay: safety, fallbacks and web transport."""
import json
from unittest import mock

import pytest
from fastapi.responses import StreamingResponse

from backend import app as web_app
from backend.vision_streaming import relay_vision_stream


class FakeStream:
    def __init__(self, events, content_type="text/event-stream"):
        self.events = events
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event.encode("utf-8")


def frame(event=None, data=None):
    return (f"event: {event}\n" if event else "") + (
        f"data: {data}\n" if data is not None else ""
    ) + "\n"


def legacy_factory(called):
    def fallback():
        called.append(True)
        yield 'data: {"type": "content", "text": "Legacy answer"}\n\n'
        yield 'event: done\ndata: {}\n\n'
    return fallback


def relay(events, *, content_type="text/event-stream"):
    called = []
    events = list(relay_vision_stream(
        object(), legacy_factory(called),
        opener=lambda request, timeout: FakeStream(events, content_type),
    ))
    return events, called


def test_streamed_delta_content_and_reasoning_are_forwarded_in_order():
    events, called = relay([
        frame(data=json.dumps({"type": "reasoning", "text": "Thinking"})),
        frame(data=json.dumps({"type": "content", "text": "Hallo "}, ensure_ascii=False)),
        frame(data=json.dumps({"type": "content", "text": "Welt"})),
        frame("metrics", '{"trace_id":"testing"}'),
        frame("done", "{}"),
    ])
    assert called == []
    assert len(events) == 5
    assert '"type": "reasoning"' in events[0]
    assert '"Hallo "' in events[1]
    assert '"Welt"' in events[2]
    assert events[3].startswith("event: metrics")
    assert events[4] == "event: done\ndata: {}\n\n"


@pytest.mark.parametrize("events, content_type", [
    ([frame("error", '{"error":"VISION_STREAM_UNSUPPORTED"}')], "text/event-stream"),
    ([frame("done", "{}")], "text/event-stream"),
    ([], "text/event-stream"),
    ([frame(data='{"choices":[]}')], "text/event-stream"),
    (['{"choices":[{"message":{"content":"not streaming"}}]}'], "application/json"),
])
def test_invalid_or_empty_stream_falls_back_before_first_token(events, content_type):
    output, called = relay(events, content_type=content_type)
    assert len(called) == 1
    assert output == list(legacy_factory([])())


@pytest.mark.parametrize("last_event", [
    frame("error", '{"error":"late failure"}'),
    "",
    TimeoutError("socket interrupted"),
])
def test_partial_output_never_replays_legacy_completion(last_event):
    output, called = relay([
        frame(data='{"type":"content","text":"partial"}'),
        last_event,
    ])
    assert called == []
    assert len(output) == 2
    assert '"partial"' in output[0]
    assert output[1].startswith("event: error")


def test_network_failure_before_first_token_uses_legacy():
    output, called = relay([TimeoutError("no first token")])
    assert len(called) == 1
    assert len(output) == 2


def test_vision_web_bridge_remains_legacy_by_default(monkeypatch):
    monkeypatch.delenv("MLX_CHAT_VISION_STREAM_ENABLED", raising=False)
    captured = []

    def agent_request(method, path, payload=None, timeout=10):
        if path.startswith("/api/profile/context"):
            return {"context": ""}
        if path == "/api/runtime/vision-route":
            return {"role": "vision", "classifications": []}
        raise AssertionError(path)

    class FakeJsonReply:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Normal vision response"}}],
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data))
        return FakeJsonReply()

    with (
        mock.patch.object(web_app, "agent_json_request", side_effect=agent_request),
        mock.patch.object(web_app, "get_json", return_value={"online": True, "model": "vision-model"}),
        mock.patch("backend.routing_observatory.observe_vision_selection"),
        mock.patch.object(web_app.urllib.request, "urlopen", side_effect=fake_urlopen),
        mock.patch("backend.weather_forecast.forecast_for_question", return_value=None),
    ):
        result = web_app.mlx_chat_stream(web_app.ChatRequest(messages=[{
            "role": "user", "content": [
                {"type": "text", "text": "What is in the image?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }]))
        chunks = list(result.body_iterator)

    assert isinstance(result, StreamingResponse)
    assert len(captured) == 1
    assert captured[0]["stream"] is False
    assert "Normal vision response" in "".join(chunks)


def test_opt_in_vision_uses_selected_vision_role_and_valid_stream_payload(monkeypatch):
    monkeypatch.setenv("MLX_CHAT_VISION_STREAM_ENABLED", "1")
    captured = []

    def agent_request(method, path, payload=None, timeout=10):
        if path.startswith("/api/profile/context"):
            return {"context": ""}
        if path == "/api/runtime/vision-route":
            return {"role": "vision_uncensored", "classifications": []}
        if path == "/api/runtime/vision-streaming/capabilities":
            return {"version": 1, "supports_explicit_vision_role": True}
        raise AssertionError(path)

    def fake_relay(request, fallback, *, timeout):
        captured.append((request.full_url, json.loads(request.data), timeout))
        yield 'data: {"type": "content", "text": "streamed"}\n\n'
        yield 'event: done\ndata: {}\n\n'

    with (
        mock.patch.object(web_app, "agent_json_request", side_effect=agent_request),
        mock.patch.object(web_app, "get_json", return_value={"online": True, "model": "vision-model"}),
        mock.patch("backend.routing_observatory.observe_vision_selection"),
        mock.patch("backend.vision_streaming.relay_vision_stream", side_effect=fake_relay),
        mock.patch("backend.weather_forecast.forecast_for_question", return_value=None),
    ):
        result = web_app.mlx_chat_stream(web_app.ChatRequest(messages=[{
            "role": "user", "content": [
                {"type": "text", "text": "Describe this picture"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }]))
        chunks = list(result.body_iterator)

    assert len(captured) == 1
    url, payload, timeout = captured[0]
    assert url.endswith("/api/runtime/chat/stream")
    assert payload["stream"] is True
    assert payload["vision_role"] == "vision_uncensored"
    assert timeout == 60
    assert len(chunks) == 2



def test_opt_in_old_agent_must_fallback_without_vision_role_stream(monkeypatch):
    monkeypatch.setenv("MLX_CHAT_VISION_STREAM_ENABLED", "1")
    legacy_calls = []

    def agent_request(method, path, payload=None, timeout=10):
        if path.startswith("/api/profile/context"):
            return {"context": ""}
        if path == "/api/runtime/vision-route":
            return {"role": "vision", "classifications": []}
        if path == "/api/runtime/vision-streaming/capabilities":
            raise RuntimeError("Agent not updated")
        raise AssertionError(path)

    class LegacyReply:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"fallback works"}}]}'

    def legacy(request, timeout):
        legacy_calls.append(request.full_url)
        return LegacyReply()

    with (
        mock.patch.object(web_app, "agent_json_request", side_effect=agent_request),
        mock.patch.object(web_app, "get_json", return_value={"online": True, "model": "vision-model"}),
        mock.patch("backend.routing_observatory.observe_vision_selection"),
        mock.patch.object(web_app.urllib.request, "urlopen", side_effect=legacy),
        mock.patch("backend.weather_forecast.forecast_for_question", return_value=None),
    ):
        result = web_app.mlx_chat_stream(web_app.ChatRequest(messages=[{
            "role": "user", "content": [
                {"type": "text", "text": "What do you see?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }]))
        chunks = list(result.body_iterator)

    assert len(legacy_calls) == 1
    assert legacy_calls[0].endswith("/api/bridge/mlx/v1/chat/completions")
    assert "fallback works" in "".join(chunks)
