"""Studio gallery flows with mocked local endpoints, both viewport sizes."""
import io
import json
import time

from PIL import Image
from playwright.sync_api import expect


IMAGE_ID = "1791579990-f04fe5195fe0"
PHOTO_ID = "a" * 24


def _png():
    data = io.BytesIO()
    Image.new("RGB", (48, 48), (35, 110, 160)).save(data, "PNG")
    return data.getvalue()


def _open_library(page):
    if page.viewport_size["width"] <= 900 and not page.locator(".sidebar").evaluate(
        "node => node.classList.contains('mobile-open')"
    ):
        page.locator("#sidebarToggle").click()
    page.locator("#sidebarLibraryButton").click()
    expect(page.locator("#nobbyLibrary")).to_be_visible()


def test_library_studio_engine_filter_and_reuse_photo(ui):
    page, _agent, _allowed = ui
    image = _png()
    now = time.time()
    assets = [
        {"kind": "image", "id": IMAGE_ID, "url": "/api/mlx/images/" + IMAGE_ID,
         "created_at": now, "persistent": True, "size_bytes": len(image)},
        {"kind": "talking_photo", "id": PHOTO_ID, "engine": "ltx-distilled",
         "url": "/api/talking-photo/videos/" + PHOTO_ID,
         "created_at": now - 60, "persistent": True, "size_bytes": 200},
    ]

    def respond(route, data):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    page.route("**/api/library/assets?limit=1000",
               lambda route: respond(route, {"assets": assets, "total": len(assets)}))
    page.route(f"**/api/mlx/images/{IMAGE_ID}",
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route(f"**/api/library/assets/talking_photo/{PHOTO_ID}/thumbnail",
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route(f"**/api/library/assets/talking_photo/{PHOTO_ID}/metadata",
               lambda route: respond(route, {
                   "kind": "talking_photo", "id": PHOTO_ID,
                   "engine": "ltx-distilled", "duration_seconds": 31.2,
                   "width": 640, "height": 640,
               }))
    page.route("**/api/talking-photo/status",
               lambda route: respond(route, {"providers": {
                   "ltx-distilled": {"ready": True, "device": "mlx/metal"},
               }}))
    page.route("**/api/mlx/audio/voices/manage",
               lambda route: respond(route, {"voices": []}))

    _open_library(page)
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator("#nobbyLibraryEngine").select_option("ltx-distilled")
    expect(page.locator(".nobby-library-card")).to_have_count(1)
    expect(page.locator(".nobby-library-card")).to_contain_text("Talking Photo")
    expect(page.locator(".nobby-library-media-details")).to_contain_text("LTX Distilled")
    page.locator('[data-library-kind="image"]').click()
    expect(page.locator("#nobbyLibraryEngine")).to_have_value("all")
    expect(page.locator(".nobby-library-card")).to_have_count(1)
    page.locator(".nobby-library-card-actions button").filter(has_text="Talking Photo").click()
    expect(page.locator("#nobbyLibrary")).to_be_hidden()
    expect(page.locator("#talkingPhotoModal")).to_be_visible()
    assert page.locator("#talkingPhotoImage").evaluate("input => input.files.length") == 1
    expect(page.locator("#talkingPhotoPreview")).to_be_visible()
    expect(page.locator("#talkingPhotoEngine")).to_have_value("ltx-distilled")
