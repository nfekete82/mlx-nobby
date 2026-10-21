"""Open local batch converter from the existing sidebar without leaving chat."""
import io
import json
from zipfile import ZipFile

from PIL import Image
from playwright.sync_api import expect


def _png():
    output = io.BytesIO()
    Image.new("RGBA", (90, 60), (40, 120, 180, 170)).save(output, "PNG")
    return output.getvalue()


def _ensure_sidebar(page):
    if page.viewport_size["width"] <= 900:
        page.locator("#sidebarToggle").click()


def test_converter_inline_zip_and_return_to_chat(ui):
    page, agent, _allowed = ui
    _ensure_sidebar(page)
    button = page.locator("#imageConverterButton")
    expect(button).to_be_visible()
    button.click()
    expect(page.locator("#imageConverterWorkspace")).to_be_visible()
    expect(page.locator("#messages")).to_be_visible()
    expect(page.locator(".composer-wrap")).to_be_visible()
    expect(page.locator(".mlx-image-converter-modal-shell")).to_be_visible()
    expect(page.locator("#imageConverterWorkspace")).to_have_attribute("aria-hidden", "false")
    bounds = page.locator(".mlx-image-converter-modal-shell").bounding_box()
    assert abs(bounds["x"] + bounds["width"] / 2 - page.viewport_size["width"] / 2) < 4
    assert page.url.endswith("/chat")  # Modal: no redirect or second page.

    inside = page.frame_locator("#imageConverterFrame")
    expect(inside.locator("#converterForm")).to_be_visible()
    inside.locator("#imageFiles").set_input_files({
        "name": "test.png", "mimeType": "image/png", "buffer": _png(),
    })
    inside.locator("#fmt").select_option("WEBP")
    with page.expect_download() as download_event:
        inside.locator("#submit").click()
    download = download_event.value
    assert download.suggested_filename == "mlx-nobby-converted.zip"
    with ZipFile(download.path()) as archive:
        assert "test.webp" in archive.namelist()
        report = json.loads(archive.read("conversion-report.json"))
        assert report[0]["status"] == "ok"

    page.locator("#imageConverterBack").click()
    expect(page.locator("#imageConverterWorkspace")).to_be_hidden()
    expect(page.locator(".composer-wrap")).to_be_visible()
    assert page.locator("#input").input_value() == ""
    assert agent.count("/api/runtime/chat/stream", "POST") == 0

    _ensure_sidebar(page)
    button.click()
    expect(page.locator("#imageConverterWorkspace")).to_be_visible()
    assert page.frame_locator("#imageConverterFrame").locator("#fmt").input_value() == "WEBP"
    inside.locator("#fmt").focus()
    page.keyboard.press("Escape")
    expect(page.locator("#imageConverterWorkspace")).to_be_hidden()
    expect(page.locator("#messages")).to_be_visible()
    _ensure_sidebar(page)
    page.locator("#newChat").click()
    expect(page.locator("#messages")).to_be_visible()
