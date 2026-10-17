"""Talking Photo UI acceptance: image import, selected face marker, LTX engine, paste."""
import io
import re

from PIL import Image, ImageDraw
from playwright.sync_api import expect


def photo():
    target = io.BytesIO()
    image = Image.new("RGB", (240, 120), (60, 74, 88))
    draw = ImageDraw.Draw(image)
    draw.ellipse((35, 24, 95, 84), fill=(218, 165, 125))
    draw.ellipse((145, 24, 205, 84), fill=(187, 142, 112))
    image.save(target, "PNG")
    return target.getvalue()


def test_talking_photo_person_selection_and_paste_keep_default_ltx(ui):
    page, _agent, _allowed = ui
    page.route(
        "**/api/talking-photo/status",
        lambda route: route.fulfill(json={
            "providers": {
                "ltx-distilled": {"ready": True},
                "ltx": {"ready": True},
                "fast": {"ready": True},
                "quality": {"ready": True},
            },
        }),
    )
    page.route("**/api/mlx/audio/voices/manage", lambda route: route.fulfill(json={"voices": []}))
    page.wait_for_function("Boolean(window.MLXTalkingPhoto && document.getElementById('talkingPhotoButton'))")
    page.locator("#talkingPhotoButton").evaluate("(button) => button.click()")
    expect(page.locator("#talkingPhotoModal")).to_be_visible()
    assert page.locator("#talkingPhotoClipboardButton").count() == 1

    field = page.locator("#talkingPhotoImage")
    field.set_input_files({"name": "two-people.png", "mimeType": "image/png", "buffer": photo()})
    preview = page.locator("#talkingPhotoPreview")
    expect(preview).to_be_visible()
    preview.evaluate("(img) => img.decode()")

    expect(page.locator("#talkingPhotoEngine")).to_have_value("ltx-distilled")
    preview.click(position={"x": 55, "y": 60})
    marker = page.locator("#talkingPhotoFocusMarker")
    expect(marker).to_be_visible()
    expect(page.locator("#talkingPhotoPersonFocusHint")).to_contain_text("LTX")
    expect(page.locator("#talkingPhotoEngine")).to_have_value("ltx-distilled")
    focus = page.evaluate("window.__focusedPosition = Boolean(document.getElementById('talkingPhotoFocusMarker').style.left)")
    assert focus
    page.locator("#talkingPhotoEngine").select_option("fast")
    expect(page.locator("#talkingPhotoPersonFocusHint")).to_contain_text("MuseTalk")

    # Replacing the image through a paste event clears the old speaker selection.
    page.evaluate("""() => {
        const file = document.getElementById('talkingPhotoImage').files[0];
        const data = new DataTransfer();
        data.items.add(file);
        document.dispatchEvent(new ClipboardEvent('paste', {
            clipboardData: data, bubbles: true, cancelable: true,
        }));
    }""")
    expect(marker).to_be_hidden()
    expect(page.locator("#talkingPhotoClipboardHint")).to_contain_text(re.compile("Bild|image", re.I))
    expect(preview).to_be_visible()
    preview.click(position={"x": 150, "y": 60})
    expect(marker).to_be_visible()
    page.locator("#talkingPhotoPersonFocusReset").click()
    expect(marker).to_be_hidden()
