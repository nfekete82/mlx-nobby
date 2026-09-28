import base64
import json

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from speech.app import SpeechRequest
from speech import streaming_routes
from agent import speech_streaming_routes as agent_streaming
from backend import speech_streaming_routes as backend_streaming


class _Result:
    def __init__(self, values=(0.0, 0.5, -0.5), sample_rate=24000):
        self.audio = np.asarray(values, dtype=np.float32)
        self.sample_rate = sample_rate


class _CloneModel:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        yield _Result()
        yield _Result((0.25, -0.25))


class _PresetModel:
    def __init__(self):
        self.kwargs = None

    def generate_custom_voice(self, **kwargs):
        self.kwargs = kwargs
        yield _Result((0.1, -0.1))


def _events(lines):
    return [json.loads(line.decode("utf-8")) for line in lines]


def test_clone_stream_uses_qwen_streaming_and_emits_pcm(monkeypatch):
    model = _CloneModel()
    monkeypatch.setattr(
        streaming_routes,
        "get_voice_profile",
        lambda voice: {
            "reference": "/tmp/pervin.wav",
            "ref_text": "Referenz",
        },
    )
    monkeypatch.setattr(streaming_routes, "get_tts_clone_model", lambda: model)

    request = SpeechRequest(input="Hallo Welt", voice="Pervin", speed=1.0)
    events = _events(streaming_routes._stream_results(request))

    assert [event["type"] for event in events] == [
        "start",
        "audio",
        "audio",
        "done",
    ]
    assert model.kwargs["stream"] is True
    assert model.kwargs["streaming_interval"] == streaming_routes._STREAM_INTERVAL
    assert model.kwargs["ref_audio"] == "/tmp/pervin.wav"
    assert model.kwargs["ref_text"] == "Referenz"

    pcm = np.frombuffer(
        base64.b64decode(events[1]["pcm"]),
        dtype="<f4",
    )
    np.testing.assert_allclose(pcm, [0.0, 0.5, -0.5])
    assert events[1]["sample_rate"] == 24000


def test_preset_stream_uses_custom_voice_streaming(monkeypatch):
    model = _PresetModel()
    monkeypatch.setattr(streaming_routes, "get_voice_profile", lambda voice: None)
    monkeypatch.setattr(streaming_routes, "get_tts_model", lambda: model)

    request = SpeechRequest(
        input="Hallo",
        voice="Serena",
        language="de",
        instruct="Warm",
        speed=1.0,
    )
    events = _events(streaming_routes._stream_results(request))

    assert events[-1]["type"] == "done"
    assert model.kwargs["speaker"] == "Serena"
    assert model.kwargs["language"] == "de"
    assert model.kwargs["stream"] is True


def test_stream_rejects_non_realtime_speed():
    request = SpeechRequest(input="Hallo", voice="Pervin", speed=1.1)
    generator = streaming_routes._stream_results(request)
    try:
        next(generator)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected HTTP 409 for non-1.0 streaming speed")


class _Upstream:
    def __init__(self, content=b'{"type":"done"}\n'):
        self._content = content
        self._offset = 0
        self.status = 200
        self.headers = {"Content-Type": "application/x-ndjson"}
        self.closed = False

    def read(self, size=-1):
        if self._offset >= len(self._content):
            return b""
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


def test_agent_streaming_proxy_forwards_bytes(monkeypatch):
    upstream = _Upstream()
    monkeypatch.setattr(agent_streaming, "_upstream_stream", lambda payload: upstream)
    app = FastAPI()
    agent_streaming.install_routes(app)

    response = TestClient(app).post(
        "/api/mlx/audio/speech/stream",
        json={"input": "Hallo"},
    )

    assert response.status_code == 200
    assert response.content == b'{"type":"done"}\n'
    assert upstream.closed is True


def test_backend_streaming_proxy_forwards_bytes(monkeypatch):
    upstream = _Upstream(b'{"type":"audio","pcm":"AA=="}\n')
    monkeypatch.setattr(
        backend_streaming.urllib.request,
        "urlopen",
        lambda request, timeout=900: upstream,
    )
    app = FastAPI()
    backend_streaming.install_routes(app, "http://127.0.0.1:8010")

    response = TestClient(app).post(
        "/api/mlx/audio/speech/stream",
        json={"input": "Hallo"},
    )

    assert response.status_code == 200
    assert b'"type":"audio"' in response.content
    assert upstream.closed is True
