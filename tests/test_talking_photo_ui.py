from pathlib import Path

from backend.talking_photo_ui import patch_chat_html


def test_talking_photo_ui_injects_scripts_once():
    source = b"<html><body><main>Nobby</main></body></html>"
    patched = patch_chat_html(source)
    assert b"/assets/chat/talking-photo.js" in patched
    assert b"/assets/chat/talking-photo-clipboard.js" in patched
    assert b"/assets/chat/talking-photo-motion.js" in patched
    assert patched.count(b"/assets/chat/talking-photo.js") == 1
    assert patched.count(b"/assets/chat/talking-photo-clipboard.js") == 1
    assert patched.count(b"/assets/chat/talking-photo-motion.js") == 1
    assert patch_chat_html(patched) == patched


def test_talking_photo_browser_module_uses_local_voice_and_job_apis():
    source = Path("frontend/assets/chat/talking-photo.js").read_text(encoding="utf-8")
    assert "/api/mlx/audio/voices/manage" in source
    assert "/api/talking-photo/status" in source
    assert "/api/talking-photo/jobs" in source
    assert "image/png,image/jpeg" in source
    assert "image/webp" not in source
    assert "video_url" in source
    assert "talkingPhotoEngine" in source
    assert "Hybrid · LTX + MuseTalk" in source
    assert "Standard · LTX direkt" in source
    assert "Fast · MuseTalk" in source
    assert "engine," in source
    assert "engineSelect.value = 'ltx'" in source
    assert "talkingPhotoActivity" in source
    assert "talkingPhotoProgressTrack" in source
    assert "talkingPhotoElapsed" in source
    assert "LTX 2.5 rendert das Video" in source
    assert "sessionStorage.setItem(JOB_STORAGE_KEY" in source
    assert "Estimated" not in source or "estimated" in source


def test_talking_photo_clipboard_module_supports_button_and_paste_shortcut():
    source = Path("frontend/assets/chat/talking-photo-clipboard.js").read_text(encoding="utf-8")
    assert "navigator.clipboard?.read" in source
    assert "document.addEventListener('paste', handlePaste)" in source
    assert "new DataTransfer()" in source
    assert "talkingPhotoImage" in source
    assert "Aus Zwischenablage einfügen" in source
    assert "⌘V" in source
    assert "createImageBitmap" in source
    assert "image/png" in source
    assert "image/jpeg" in source


def test_talking_photo_motion_module_adds_natural_mode_to_job_payload():
    source = Path("frontend/assets/chat/talking-photo-motion.js").read_text(encoding="utf-8")
    assert "talkingPhotoMotion" in source
    assert "Natürlich · Kopf, Augen & Oberkörper" in source
    assert "Nur Lippen · schneller" in source
    assert "payload.motion" in source
    assert "LTX 2.5" in source
    assert "Natürliche Bewegung wird" in source
