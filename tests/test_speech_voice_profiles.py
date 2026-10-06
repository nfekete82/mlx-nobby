from pathlib import Path


def test_speech_service_supports_clone_profiles():
    source = Path("speech/app.py").read_text(encoding="utf-8")

    assert "Qwen3-TTS-12Hz-1.7B-Base-6bit" in source
    assert "def get_voice_profile" in source
    assert '"reference.wav"' in source
    assert '"transcript.txt"' in source
    assert "get_tts_clone_model" in source
    assert "ref_audio=str(profile" in source
    assert 'ref_text=profile["ref_text"]' in source


def test_voice_profiles_stay_private():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "speech/voices/" in ignore


def test_all_lazy_speech_models_use_runtime_memory_guard():
    source = Path("speech/app.py").read_text(encoding="utf-8")

    assert 'ensure_model_load_allowed(\n                    "speech-stt"' in source
    assert 'ensure_model_load_allowed(\n                    "speech-tts"' in source
    assert 'ensure_model_load_allowed(\n                    "speech-tts-clone"' in source


def test_router_and_main_model_launchers_use_runtime_memory_guard():
    main = Path("scripts/mlx-server-start").read_text(encoding="utf-8")
    router = Path("scripts/mlx-router-start").read_text(encoding="utf-8")
    template = Path(
        "launchd/templates/de.nobby.mlx-router.plist.template"
    ).read_text(encoding="utf-8")

    assert "runtime-model-guard.py" in main
    assert "--workload chat" in main
    assert "runtime-model-guard.py" in router
    assert "--workload router" in router
    assert "scripts/mlx-router-start" in template
