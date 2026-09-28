import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


QUALITY = {
    "stable": {"temperature": 0.45, "top_k": 20, "top_p": 0.85},
    "natural": {"temperature": 0.65, "top_k": 30, "top_p": 0.90},
    "expressive": {"temperature": 0.85, "top_k": 50, "top_p": 0.95},
}


def _write_wav(path: Path, seconds=0.1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * int(24000 * seconds))


def _load_module(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    config = tmp_path / "voice-manager.json"
    stub = types.ModuleType("speech.app")

    def profile_name(value):
        value = str(value or "").strip().lower()
        return re.sub(r"[^a-z0-9_-]+", "-", value).strip("-")

    def list_profiles():
        if not voices_dir.is_dir():
            return []
        return sorted(
            item.name
            for item in voices_dir.iterdir()
            if item.is_dir()
            and (item / "reference.wav").is_file()
            and (item / "transcript.txt").is_file()
        )

    def metadata(voice):
        path = voices_dir / profile_name(voice) / "profile.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def label(voice):
        name = profile_name(voice)
        return str(metadata(name).get("label") or name.replace("-", " ").title())

    def quality(voice):
        value = str(metadata(voice).get("quality") or "natural")
        return value if value in QUALITY else "natural"

    def profile(voice):
        name = profile_name(voice)
        directory = voices_dir / name
        reference = directory / "reference.wav"
        transcript = directory / "transcript.txt"
        if not reference.is_file() or not transcript.is_file():
            return None
        return {
            "name": name,
            "reference": reference,
            "transcript": transcript,
            "ref_text": transcript.read_text(encoding="utf-8").strip(),
        }

    def default_voice():
        try:
            configured = json.loads(config.read_text(encoding="utf-8")).get("default_voice")
        except (FileNotFoundError, json.JSONDecodeError):
            configured = None
        available = {label(name) for name in list_profiles()} | {"Serena"}
        return configured if configured in available else "Serena"

    stub.FFMPEG = "/usr/bin/false"
    stub.TTS_VOICES_DIR = voices_dir
    stub.VOICE_MANAGER_CONFIG = config
    stub.VOICE_QUALITY_MODES = tuple(QUALITY)
    stub._voice_profile_name = profile_name
    stub.clone_generation_options = lambda voice=None: dict(QUALITY[quality(voice)])
    stub.current_default_voice = default_voice
    stub.get_voice_profile = profile
    stub.get_voice_quality = quality
    stub.list_voice_profiles = list_profiles
    stub.voice_profile_label = label
    stub.voice_profile_metadata = metadata

    monkeypatch.setitem(sys.modules, "speech.app", stub)
    source = Path(__file__).parents[1] / "speech" / "voice_manager_routes.py"
    spec = importlib.util.spec_from_file_location(
        f"voice_manager_routes_test_{id(tmp_path)}",
        source,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, voices_dir, config


def _seed_voice(voices_dir: Path, name="nobby", label="Nobby", quality="natural"):
    directory = voices_dir / name
    directory.mkdir(parents=True, exist_ok=True)
    _write_wav(directory / "reference.wav")
    (directory / "transcript.txt").write_text("Hallo Referenz\n", encoding="utf-8")
    (directory / "profile.json").write_text(
        json.dumps({"label": label, "quality": quality}),
        encoding="utf-8",
    )


def test_manage_update_default_rename_and_delete(tmp_path, monkeypatch):
    module, voices_dir, config = _load_module(tmp_path, monkeypatch)
    _seed_voice(voices_dir)
    app = FastAPI()
    module.install_routes(app)
    client = TestClient(app)

    listing = client.get("/v1/audio/voices/manage")
    assert listing.status_code == 200
    clone = next(item for item in listing.json()["voices"] if item["id"] == "Nobby")
    assert clone["quality"] == "natural"
    assert clone["duration_seconds"] == 0.1

    response = client.put("/v1/audio/voice-default", json={"voice": "Nobby"})
    assert response.status_code == 200
    assert response.json()["default"] == "Nobby"

    response = client.put(
        "/v1/audio/voices/Nobby",
        json={
            "name": "Nobby Prime",
            "transcript": "Neue Referenz",
            "quality": "stable",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "Nobby Prime"
    assert payload["quality"] == "stable"
    assert payload["sampling"]["temperature"] == 0.45
    assert not (voices_dir / "nobby").exists()
    assert (voices_dir / "nobby-prime" / "transcript.txt").read_text().strip() == "Neue Referenz"
    assert json.loads(config.read_text())["default_voice"] == "Nobby Prime"

    response = client.delete("/v1/audio/voices/Nobby%20Prime")
    assert response.status_code == 200
    assert response.json()["default"] == "Serena"
    assert not (voices_dir / "nobby-prime").exists()


def test_import_is_atomic_and_creates_local_profile(tmp_path, monkeypatch):
    module, voices_dir, _config = _load_module(tmp_path, monkeypatch)

    def fake_process(_source, target):
        _write_wav(target, seconds=0.2)

    monkeypatch.setattr(module, "_process_reference", fake_process)
    app = FastAPI()
    module.install_routes(app)
    client = TestClient(app)

    response = client.post(
        "/v1/audio/voices/import",
        data={
            "name": "Test Voice",
            "transcript": "Das ist eine Referenz.",
            "quality": "expressive",
        },
        files={"file": ("voice.opus", b"fake audio", "audio/ogg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "Test Voice"
    assert payload["quality"] == "expressive"
    assert payload["duration_seconds"] == 0.2
    assert (voices_dir / "test-voice" / "reference.wav").is_file()
    assert not list(voices_dir.glob(".voice-import-*"))


def test_symlink_profile_is_rejected(tmp_path, monkeypatch):
    module, voices_dir, _config = _load_module(tmp_path, monkeypatch)
    voices_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (voices_dir / "evil").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")

    with pytest.raises(Exception) as exc_info:
        module._managed_profile_dir("evil")
    assert getattr(exc_info.value, "status_code", None) == 400
