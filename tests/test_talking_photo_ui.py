from pathlib import Path

from backend.talking_photo_ui import patch_chat_html


def test_talking_photo_ui_injects_script_once():
    source = b"<html><body><main>Nobby</main></body></html>"
    patched = patch_chat_html(source)
    assert b"/assets/chat/talking-photo.js" in patched
    assert patched.count(b"/assets/chat/talking-photo.js") == 1
    assert patch_chat_html(patched) == patched


def test_talking_photo_browser_module_uses_local_voice_and_job_apis():
    source = Path("frontend/assets/chat/talking-photo.js").read_text(encoding="utf-8")
    assert "/api/mlx/audio/voices/manage" in source
    assert "/api/talking-photo/status" in source
    assert "/api/talking-photo/jobs" in source
    assert "image/png,image/jpeg" in source
    assert "image/webp" not in source
    assert "video_url" in source
