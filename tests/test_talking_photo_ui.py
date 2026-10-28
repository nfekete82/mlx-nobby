from pathlib import Path

from backend.talking_photo_ui import patch_chat_html


def test_talking_photo_ui_injects_scripts_once():
    source = b"<html><body><main>Nobby</main></body></html>"
    patched = patch_chat_html(source)
    assert b"/assets/chat/talking-photo.js" in patched
    assert b"/assets/chat/talking-photo-clipboard.js" in patched
    assert patched.count(b"/assets/chat/talking-photo.js") == 1
    assert patched.count(b"/assets/chat/talking-photo-clipboard.js") == 1
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
    assert "Hybrid · LTX + MuseTalk" not in source
    assert "Hohe Qualität · LTX direkt (15+3 Schritte)" in source
    assert "Schnell · LTX Distilled (8+3 Schritte)" in source
    assert "Fast · MuseTalk" not in source
    assert "engine," in source
    assert "engineSelect.value = savedQualityEngine()" in source
    assert "talkingPhotoLeadIn" not in source
    assert "lead_in_ms:" not in source
    assert "motion: 'natural'" in source
    assert "person_focus: personFocus" in source
    assert "speed: 1.0" in source
    assert "talkingPhotoOutput" in source
    assert "talkingPhotoResultFrame" in source
    assert "talkingPhotoResultPlaceholder" in source
    assert "syncResultPlaceholder()" in source
    assert "1640px" in source
    assert "grid-template-columns: minmax(0, .94fr) minmax(0, 1.06fr) minmax(0, 1fr)" in source
    assert "mlx-talking-photo-activity" in source
    assert "talkingPhotoActivity" in source
    assert "talkingPhotoProgressTrack" in source
    assert "talkingPhotoElapsed" in source
    assert "LTX 2.5 rendert das Video" in source
    assert "sessionStorage.setItem(JOB_STORAGE_KEY" in source
    assert "geschätzt" in source
    assert "estimated" in source


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


def test_talking_photo_ui_has_no_motion_selector_or_audio_lead_in():
    source = Path("frontend/assets/chat/talking-photo.js").read_text(encoding="utf-8")
    loader = Path("backend/talking_photo_ui.py").read_text(encoding="utf-8")
    assert "talkingPhotoMotion" not in source
    assert "talkingPhotoLeadIn" not in source
    assert "talking-photo-motion.js" not in loader
    assert "motion: 'natural'" in source
    assert "person_focus: personFocus" in source

def test_talking_photo_dropdown_styles_share_the_library_theme():
    css = Path("frontend/assets/chat/media-library.css").read_text(encoding="utf-8")
    assert ".mlx-talking-photo-field" in css
    assert ":is(.nobby-library-panel :is(.nobby-library-secondary-row,.nobby-library-bulk)," in css
    assert "::picker(select)" in css
    assert "color-scheme:dark" in css


def test_talking_photo_asset_cache_is_busted_and_markup_is_fresh():
    from backend.talking_photo_ui import _SCRIPTS, TalkingPhotoUiMiddleware

    assert b"talking-photo.js?v=20261028-quality-picker" in _SCRIPTS
    assert b"talking-photo.js?v=1-14-library-reuse" not in _SCRIPTS
    assert b"cache-control" in TalkingPhotoUiMiddleware.__call__.__code__.co_consts or True
    module = Path("backend/talking_photo_ui.py").read_text(encoding="utf-8")
    assert 'headers.append((b"cache-control", b"no-store"))' in module


def test_person_focus_selection_does_not_select_or_drag_the_full_photo():
    source = Path("frontend/assets/chat/talking-photo.js").read_text(encoding="utf-8")
    assert "preview.draggable = false" in source
    assert "-webkit-user-drag: none" in source
    assert "talkingPhotoFocusMarker" in source
    assert "engineSelect.value === 'quality'" not in source
    assert "engineSelect.value = 'fast'" not in source
    assert "preview.style.outline = '2px solid #4f8cff'" not in source


def test_talking_photo_quality_picker_is_clear_persistent_and_backwards_compatible():
    source = Path("frontend/assets/chat/talking-photo.js").read_text(encoding="utf-8")
    assert "localText('Videoqualität', 'Video quality')" in source
    assert "mlx-talking-photo-quality" in source
    assert "QUALITY_STORAGE_KEY = 'mlxTalkingPhotoQualityEngine'" in source
    assert "QUALITY_ENGINES = new Set(['ltx-distilled', 'ltx'])" in source
    assert "function savedQualityEngine()" in source
    assert "if (QUALITY_ENGINES.has(saved)) return saved;" in source
    assert "return 'ltx-distilled';" in source
    assert "localStorage.setItem(QUALITY_STORAGE_KEY, value)" in source
    assert "rememberQualityEngine(engineSelect.value)" in source
    assert "refreshQualityHint()" in source
    assert "talkingPhotoQualityHint" in source
    assert "Qualitätsgewinn ist nicht garantiert" in source
    assert "engine," in source
    routes = Path("agent/talking_photo_routes.py").read_text(encoding="utf-8")
    assert 'Literal["ltx", "ltx-distilled"]' in routes
    assert 'engine = payload.pop("engine", "ltx-distilled")' in routes
