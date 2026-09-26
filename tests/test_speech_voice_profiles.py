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
