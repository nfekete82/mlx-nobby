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
    page.route("**/api/library/organize",
               lambda route: respond(route, {"version": 1, "favorites": [], "collections": []}))
    page.route("**/api/library/workflows",
               lambda route: respond(route, {"version": 1, "links": {}}))
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


def test_library_collections_favorites_multiselect_and_jobs_in_system_group(ui):
    page, _agent, _allowed = ui
    image = _png()
    now = time.time()
    images = [
        {"kind": "image", "id": IMAGE_ID, "url": "/api/mlx/images/" + IMAGE_ID,
         "created_at": now, "persistent": True, "size_bytes": len(image)},
        {"kind": "talking_photo", "id": PHOTO_ID, "engine": "ltx-distilled",
         "url": "/api/talking-photo/videos/" + PHOTO_ID,
         "created_at": now - 30, "persistent": True, "size_bytes": 100},
    ]
    record = {"version": 1, "favorites": [], "collections": []}
    operations = []

    def send(route, body):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def post_collection(route):
        item = {"id": "d" * 16, "name": route.request.post_data_json["name"], "items": []}
        record["collections"].append(item)
        send(route, item)

    def post_batch(route):
        data = route.request.post_data_json
        keys = [i["kind"] + ":" + i["id"] for i in data["items"]]
        operations.append(data["operation"])
        if data["operation"] == "favorite":
            record["favorites"] = sorted(set(record["favorites"]) | set(keys))
        if data["operation"] == "add_collection":
            record["collections"][0]["items"] = sorted(set(record["collections"][0]["items"]) | set(keys))
        if data["operation"] == "remove_collection":
            record["collections"][0]["items"] = [
                key for key in record["collections"][0]["items"] if key not in keys
            ]
        send(route, {"updated": len(keys), "operation": data["operation"],
                     "organization": record})

    page.route("**/api/library/assets?limit=1000",
               lambda route: send(route, {"assets": images, "total": 2}))
    page.route("**/api/library/organize",
               lambda route: send(route, record))
    page.route("**/api/library/workflows",
               lambda route: send(route, {"version": 1, "links": {}}))
    page.route("**/api/library/organize/collections",
               post_collection)
    page.route("**/api/library/organize/batch", post_batch)
    page.route("**/api/mlx/images/" + IMAGE_ID,
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route("**/api/library/assets/talking_photo/" + PHOTO_ID + "/thumbnail",
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route("**/api/library/assets/talking_photo/" + PHOTO_ID + "/metadata",
               lambda route: send(route, {"id": PHOTO_ID, "kind": "talking_photo",
                                          "engine": "ltx-distilled", "duration_seconds": 25}))

    _open_library(page)
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator(".nobby-library-star").first.click()
    assert operations == ["favorite"]
    page.locator("#nobbyLibraryCollectionFilter").select_option("favorites")
    expect(page.locator(".nobby-library-card")).to_have_count(1)
    page.locator("#nobbyLibraryCollectionFilter").select_option("all")
    page.once("dialog", lambda dialog: dialog.accept("Reisen"))
    page.locator("#nobbyLibraryNewCollection").click()
    expect(page.locator("#nobbyLibraryCollectionFilter")).to_have_value("d" * 16)
    page.locator("#nobbyLibraryCollectionFilter").select_option("all")
    page.locator("#nobbyLibrarySelectVisible").click()
    expect(page.locator("#nobbyLibrarySelectedCount")).to_contain_text("2")
    page.locator("#nobbyLibraryAddSelected").click()
    assert "add_collection" in operations
    page.locator("#nobbyLibraryCollectionFilter").select_option("d" * 16)
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator("#nobbyLibraryClearSelection").click()
    expect(page.locator("#nobbyLibraryBulk")).to_be_hidden()

    page.locator("#nobbyLibraryClose").click()
    if page.viewport_size["width"] <= 900 and not page.locator(".sidebar").evaluate(
        "node => node.classList.contains('mobile-open')"
    ):
        page.locator("#sidebarToggle").click()
    page.locator("#sidebarSystemTools summary").click()
    expect(page.locator("#sidebarJobsButton")).to_be_visible()
    assert page.locator("#sidebarJobsButton").evaluate(
        "node => Boolean(node.closest('#sidebarSystemTools'))"
    )


def test_media_studio_image_to_video_prefill_and_source_navigation(ui):
    """Only prepares the existing video composer; never starts a render automatically."""
    page, _agent, _allowed = ui
    image = _png()
    now = time.time()
    video_id = "c" * 24
    assets = [
        {"kind": "image", "id": IMAGE_ID, "url": "/api/mlx/images/" + IMAGE_ID,
         "created_at": now, "persistent": True, "size_bytes": len(image)},
        {"kind": "video", "id": video_id, "url": "/api/mlx/videos/" + video_id,
         "created_at": now - 20, "persistent": True, "size_bytes": 400},
    ]

    def send(route, data):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    page.route("**/api/library/assets?limit=1000",
               lambda route: send(route, {"assets": assets, "total": 2}))
    page.route("**/api/library/organize",
               lambda route: send(route, {"version": 1, "favorites": [], "collections": []}))
    page.route("**/api/library/workflows",
               lambda route: send(route, {"version": 1, "links": {
                   "video:" + video_id: "image:" + IMAGE_ID,
               }}))
    page.route("**/api/mlx/images/" + IMAGE_ID,
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route("**/api/library/assets/video/" + video_id + "/thumbnail",
               lambda route: route.fulfill(status=200, content_type="image/png", body=image))
    page.route("**/api/library/assets/video/" + video_id + "/metadata",
               lambda route: send(route, {
                   "kind": "video", "id": video_id, "duration_seconds": 5.0,
               }))

    _open_library(page)
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    expect(page.locator(".nobby-library-parent-link")).to_have_count(1)
    page.locator(".nobby-library-parent-link").click()
    expect(page.locator(".nobby-library-preview-body img")).to_be_visible()
    page.locator(".nobby-library-preview-close").click()

    page.locator(".nobby-library-card").filter(has=page.locator(".nobby-library-lineage-count")).locator(
        ".nobby-library-card-actions button"
    ).filter(has_text="Video").click()
    expect(page.locator("#nobbyLibrary")).to_be_hidden()
    expect(page.locator("#attachmentBar .image-attachment-chip")).to_have_count(1)
    assert "video" in page.locator("#input").input_value().lower()
    assert page.evaluate("""() => {
        const file = window.MLXChatAttachments.getAttachments().find(f => f.kind === "image");
        return file?.library_source?.id;
    }""") == IMAGE_ID


def test_library_local_date_and_size_sorting(ui):
    """Filters must combine with existing media kind without an ML or network search."""
    page, _agent, _allowed = ui
    now = time.time()
    old_image = "1791579990-aaaaaaaaaaaa"
    recent_image = IMAGE_ID
    video_id = PHOTO_ID
    items = [
        {"kind": "image", "id": old_image, "url": "/api/mlx/images/" + old_image,
         "created_at": now - 40 * 86400, "persistent": True, "size_bytes": 500},
        {"kind": "image", "id": recent_image, "url": "/api/mlx/images/" + recent_image,
         "created_at": now - 120, "persistent": True, "size_bytes": 100},
        {"kind": "video", "id": video_id, "url": "/api/mlx/videos/" + video_id,
         "created_at": now - 3 * 86400, "persistent": True, "size_bytes": 1000},
    ]

    def send(route, data):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    page.route("**/api/library/assets?limit=1000",
               lambda route: send(route, {"assets": items, "total": len(items)}))
    page.route("**/api/library/organize",
               lambda route: send(route, {"version": 1, "favorites": [], "collections": []}))
    page.route("**/api/library/workflows",
               lambda route: send(route, {"version": 1, "links": {}}))
    _open_library(page)
    expect(page.locator(".nobby-library-card")).to_have_count(3)
    page.locator("#nobbyLibrarySort").select_option("largest")
    assert page.locator(".nobby-library-card").evaluate_all(
        "nodes => nodes.map(n => n.textContent.includes('Video'))"
    )[0]
    page.locator("#nobbyLibraryDateFilter").select_option("month")
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator("#nobbyLibraryDateFilter").select_option("week")
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator("#nobbyLibraryDateFilter").select_option("today")
    expect(page.locator(".nobby-library-card")).to_have_count(1)
    page.locator("#nobbyLibraryDateFilter").select_option("all")
    page.locator('[data-library-kind="image"]').click()
    expect(page.locator(".nobby-library-card")).to_have_count(2)
    page.locator("#nobbyLibrarySort").select_option("smallest")
    assert page.locator(".nobby-library-card").first.inner_text().find(recent_image) >= 0
