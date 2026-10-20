"""Pinned benchmark streams must never invoke chat-role model switching."""
from contextlib import nullcontext
import json
from unittest import mock

from fastapi.testclient import TestClient
from agent import app as agent_app


DARK = "jancirnodziewiaty/Dark-Scarlett-27B-v2.0-oQ4e-mtp"


class FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter([
            b'data: {"choices":[{"delta":{"content":"Reply"}}]}\n\n',
            b'data: [DONE]\n\n',
        ])


def test_stream_pin_uses_requested_running_model_without_role_switch():
    upstream_models = []

    def fake_open(req, timeout=900):
        upstream_models.append(json.loads(req.data.decode("utf-8"))["model"])
        return FakeStream()

    with mock.patch.object(agent_app, "load_config",
                           return_value={"MODEL": DARK, "PORT": "8000", "THINKING": "false"}), \
         mock.patch.object(agent_app, "find_server_pid", return_value=7766), \
         mock.patch.object(agent_app, "ensure_model_for_role", side_effect=AssertionError("role switch forbidden")) as role_switch, \
         mock.patch.object(agent_app, "switch_model_runtime", side_effect=AssertionError("runtime switch forbidden")) as runtime_switch, \
         mock.patch.object(agent_app.runtime_coordinator, "chat_runtime", return_value=nullcontext()), \
         mock.patch.object(agent_app.urllib.request, "urlopen", side_effect=fake_open):
        with TestClient(agent_app.app) as client:
            response = client.post("/api/runtime/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True, "auto_route": False,
                "pin_active_model": DARK, "pin_active_pid": 7766,
            })
    assert response.status_code == 200
    assert '"text": "Reply"' in response.text
    assert upstream_models == [DARK]
    role_switch.assert_not_called()
    runtime_switch.assert_not_called()


def test_stream_pin_rejects_model_mismatch_without_generation_or_switch():
    for configured_model, actual_pid, auto_route in (
        ("local/Qwen3.8", 7766, False),
        (DARK, 7767, False),
        (DARK, 7766, True),
    ):
        with mock.patch.object(agent_app, "load_config",
                               return_value={"MODEL": configured_model, "PORT": "8000"}), \
             mock.patch.object(agent_app, "find_server_pid", return_value=actual_pid), \
             mock.patch.object(agent_app, "ensure_model_for_role") as ensure, \
             mock.patch.object(agent_app, "switch_model_runtime") as switch, \
             mock.patch.object(agent_app.runtime_coordinator, "chat_runtime", return_value=nullcontext()), \
             mock.patch.object(agent_app.urllib.request, "urlopen") as urlopen:
            with TestClient(agent_app.app) as client:
                response = client.post("/api/runtime/chat/stream", json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True, "auto_route": auto_route,
                    "pin_active_model": DARK, "pin_active_pid": 7766,
                })
        assert response.status_code == 200
        assert "event: error" in response.text
        ensure.assert_not_called()
        switch.assert_not_called()
        urlopen.assert_not_called()


def test_regular_stream_without_pin_keeps_existing_role_resolution():
    with mock.patch.object(agent_app, "ensure_model_for_role",
                           return_value={"resolved": {"repo": "local/Qwen3.8", "alias": "qwen"}}) as ensure, \
         mock.patch.object(agent_app, "load_config",
                           return_value={"PORT": 8000, "THINKING": "false"}), \
         mock.patch.object(agent_app.runtime_coordinator, "chat_runtime", return_value=nullcontext()), \
         mock.patch.object(agent_app.urllib.request, "urlopen", return_value=FakeStream()):
        with TestClient(agent_app.app) as client:
            response = client.post("/api/runtime/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "auto_route": False,
            })
    assert response.status_code == 200
    assert '"text": "Reply"' in response.text
    ensure.assert_called_once_with("chat")
