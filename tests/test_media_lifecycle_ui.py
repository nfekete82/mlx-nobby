from pathlib import Path

from backend.media_lifecycle_routes import (
    MEDIA_LIFECYCLE_SCRIPT,
    inject_media_lifecycle_script,
)


def test_media_lifecycle_script_is_injected_once():
    source = b"<html><body><main>Nobby</main></body></html>"
    patched = inject_media_lifecycle_script(source)
    assert MEDIA_LIFECYCLE_SCRIPT in patched
    assert patched.count(MEDIA_LIFECYCLE_SCRIPT) == 1
    assert inject_media_lifecycle_script(patched) == patched


def test_browser_cleanup_tracks_downloads_pagehide_and_talking_photo():
    source = Path("frontend/assets/chat/media-lifecycle.js").read_text(encoding="utf-8")
    assert "/api/mlx/media-lifecycle/persist" in source
    assert "/api/mlx/media-lifecycle/discard" in source
    assert "window.addEventListener('pagehide'" in source
    assert "navigator.sendBeacon" in source
    assert "MutationObserver" in source
    assert "/api/talking-photo/jobs/${encodeURIComponent(ref.id)}/keep" in source
    assert "/api/talking-photo/jobs/${encodeURIComponent(ref.id)}/discard" in source
    assert "Nicht gespeicherte Ergebnisse werden beim Schließen automatisch gelöscht." in source
    assert "item.kind !== 'talking_photo'" in source


def test_browser_cleanup_recognizes_managed_media_urls():
    source = Path("frontend/assets/chat/media-lifecycle.js").read_text(encoding="utf-8")
    assert "images\\/(\\d{10}-[0-9a-f]{12})" in source
    assert "videos\\/([0-9a-f]{24})" in source
    assert "talking-photo\\/videos\\/([0-9a-f]{24})" in source
