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


def test_speech_service_can_release_idle_models_for_media_handoff():
    source = Path("speech/app.py").read_text(encoding="utf-8")
    streaming = Path("speech/streaming_routes.py").read_text(encoding="utf-8")

    assert '@app.post("/unload")' in source
    assert '"active_generation": _active_requests > 0' in source
    assert "def speech_activity" in source
    assert "_clear_mlx_cache()" in source
    assert "with speech_activity():" in streaming
