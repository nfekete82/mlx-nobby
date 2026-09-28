from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from speech import alignment_routes


def install_app(tmp_path, monkeypatch, *, result=None, generate_error=None):
    root = tmp_path / "shorts"
    root.mkdir()
    monkeypatch.setattr(alignment_routes, "SHORTS_ROOT", root)

    calls = []

    class Model:
        def generate(self, path, **kwargs):
            calls.append((path, kwargs))
            if generate_error is not None:
                raise generate_error
            return result

    def fake_convert(source, ffmpeg):
        assert source.is_relative_to(root)
        wav = tmp_path / "converted.wav"
        wav.write_bytes(b"wav")
        return wav

    monkeypatch.setattr(alignment_routes, "_convert_to_wav", fake_convert)
    app = FastAPI()
    alignment_routes.install_routes(
        app,
        get_model=lambda: Model(),
        ffmpeg="/fake/ffmpeg",
        model_name="whisper-test",
    )
    return TestClient(app), root, calls


def test_serializer_supports_mlx_audio_result_shape():
    result = SimpleNamespace(
        text="Hallo Berlin",
        language="de",
        segments=[{
            "words": [
                {"word": " Hallo", "start": 0.10, "end": 0.43, "probability": 0.97},
                {"word": " Berlin", "start": 0.45, "end": 0.91, "probability": 0.95},
            ],
        }],
    )

    payload = alignment_routes._serialize_result(result, "whisper-test")

    assert payload == {
        "text": "Hallo Berlin",
        "language": "de",
        "model": "whisper-test",
        "words": [
            {"word": "Hallo", "start": 0.10, "end": 0.43, "probability": 0.97},
            {"word": "Berlin", "start": 0.45, "end": 0.91, "probability": 0.95},
        ],
    }


def test_alignment_route_requests_real_whisper_word_timestamps(tmp_path, monkeypatch):
    result = {
        "text": "Hallo Berlin",
        "language": "de",
        "segments": [{
            "words": [
                {"word": "Hallo", "start": 0.1, "end": 0.4, "probability": 0.9},
                {"word": "Berlin", "start": 0.5, "end": 0.9, "probability": 0.9},
            ],
        }],
    }
    client, root, calls = install_app(tmp_path, monkeypatch, result=result)
    source = root / "job-one" / "voiceover.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")

    response = client.post(
        "/v1/audio/align",
        json={
            "source_path": str(source),
            "text": "Hallo Berlin",
            "language": "de",
        },
    )

    assert response.status_code == 200, response.text
    assert [word["word"] for word in response.json()["words"]] == ["Hallo", "Berlin"]
    assert len(calls) == 1
    path, kwargs = calls[0]
    assert path.endswith("converted.wav")
    assert kwargs["language"] == "de"
    assert kwargs["word_timestamps"] is True
    assert kwargs["initial_prompt"] == "Hallo Berlin"
    assert not Path(path).exists()


def test_alignment_route_rejects_audio_outside_shorts_root(tmp_path, monkeypatch):
    client, _root, calls = install_app(tmp_path, monkeypatch, result={})
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"mp3")

    response = client.post(
        "/v1/audio/align",
        json={"source_path": str(outside), "text": "Hallo", "language": "de"},
    )

    assert response.status_code == 422
    assert calls == []


def test_alignment_route_fails_cleanly_when_whisper_has_no_words(tmp_path, monkeypatch):
    client, root, _calls = install_app(
        tmp_path,
        monkeypatch,
        result={"text": "", "language": "de", "segments": []},
    )
    source = root / "job-two" / "voiceover.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")

    response = client.post(
        "/v1/audio/align",
        json={"source_path": str(source), "text": "Hallo", "language": "de"},
    )

    assert response.status_code == 500
    assert "keine Wort-Zeitstempel" in response.json()["detail"]


def test_source_validation_requires_real_supported_audio(tmp_path, monkeypatch):
    root = tmp_path / "shorts"
    root.mkdir()
    monkeypatch.setattr(alignment_routes, "SHORTS_ROOT", root)
    bad = root / "voiceover.txt"
    bad.write_text("not audio", encoding="utf-8")

    with pytest.raises(Exception):
        alignment_routes._validated_source(str(bad))
