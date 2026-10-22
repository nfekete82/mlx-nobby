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

    # The modal must win hit-testing at the same screen coordinates as the composer.
    front_layer = page.evaluate("""() => {
        const panel = document.getElementById('imageConverterWorkspace');
        const shell = document.querySelector('.mlx-image-converter-modal-shell');
        const r = shell.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2,
                                              r.top + r.height / 2);
        return {
            bodyChild: panel.parentElement === document.body,
            foreground: shell.contains(top),
            chatInert: document.querySelector('.app').inert,
        };
    }""")
    assert front_layer == {"bodyChild": True, "foreground": True, "chatInert": True}

    inside = page.frame_locator("#imageConverterFrame")
    expect(inside.locator("#converterForm")).to_be_visible()

    if page.viewport_size["width"] >= 900:
        sizes = inside.locator("html").evaluate(
            "node => ({content: node.scrollHeight, available: node.clientHeight})"
        )
        assert sizes["content"] <= sizes["available"] + 1, sizes
    inside.locator("#imageFiles").set_input_files({
        "name": "test.png", "mimeType": "image/png", "buffer": _png(),
    })
    expect(inside.locator("#dropzone")).to_have_class("has-files")
    expect(inside.locator(".dropzone-file")).to_have_count(1)
    expect(inside.locator(".dropzone-file-name")).to_have_text("test.png")
    expect(inside.locator(".dropzone-thumb-image")).to_be_visible()
    expect(inside.locator("#dropzoneEmpty")).to_be_hidden()
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
    assert not page.evaluate("document.querySelector('.app').inert")
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


def test_converter_language_matches_chat_and_keeps_uploaded_files(ui):
    page, _agent, _allowed = ui
    _ensure_sidebar(page)
    page.locator("#imageConverterButton").click()
    inside = page.frame_locator("#imageConverterFrame")

    # MLX-Nobby's configured default is English.
    expect(page.locator("#imageConverterWorkspaceTitle")).to_have_text("Image converter")
    expect(inside.locator('[data-converter-i18n="format"]')).to_have_text("Output format")
    expect(inside.locator("#selection")).to_have_text("No files selected")

    inside.locator("#imageFiles").set_input_files({
        "name": "bild.png", "mimeType": "image/png", "buffer": _png(),
    })
    expect(inside.locator("#selection")).to_contain_text("1 file")

    # Switching the main app language updates the iframe in place.
    page.evaluate("window.MLXI18n.setLanguage('de')")
    expect(page.locator("#imageConverterWorkspaceTitle")).to_have_text("Bildkonverter")
    expect(inside.locator('[data-converter-i18n="format"]')).to_have_text("Zielformat")
    expect(inside.locator('[data-converter-i18n="drop"]')).to_contain_text("Bilder hier")
    expect(inside.locator("#selection")).to_contain_text("1 Datei")
    expect(inside.locator(".dropzone-file-name")).to_have_text("bild.png")
    assert inside.locator("#imageFiles").evaluate("input => input.files.length") == 1

    page.evaluate("window.MLXI18n.setLanguage('en')")
    expect(page.locator("#imageConverterWorkspaceTitle")).to_have_text("Image converter")
    expect(inside.locator('[data-converter-i18n="submit"]')).to_have_text(
        "Convert and download ZIP"
    )
    expect(inside.locator("#selection")).to_contain_text("1 file")
    assert inside.locator("#imageFiles").evaluate("input => input.files.length") == 1


def test_converter_dropzone_shows_dragged_batch_and_more_count(ui):
    page, _agent, _allowed = ui
    _ensure_sidebar(page)
    page.locator("#imageConverterButton").click()
    inside = page.frame_locator("#imageConverterFrame")
    drop = inside.locator("#dropzone")
    expect(inside.locator("#dropzoneEmpty")).to_be_visible()

    # Element visibility alone does not mean its synchronous JS handlers
    # are installed. On slower mobile CI the iframe may still be parsing.
    page.wait_for_function("""() => {
        const frame = document.getElementById('imageConverterFrame');
        try {
            return frame?.contentWindow?.location?.pathname === '/converter'
                && frame.contentDocument?.readyState === 'complete';
        } catch (_) {
            return false;
        }
    }""")

    # Exercise the actual HTML5 drop handler, not just file input change.
    drop.evaluate("""element => {
        const transfer = new DataTransfer();
        for (let index = 1; index <= 5; index += 1) {
            transfer.items.add(new File(['test'], 'bild-' + index + '.png', {
                type: 'image/png'
            }));
        }
        element.dispatchEvent(new DragEvent('drop', {
            dataTransfer: transfer, bubbles: true, cancelable: true
        }));
    }""")

    expect(drop).to_have_class("has-files")
    expect(inside.locator("#dropzoneEmpty")).to_be_hidden()
    expect(inside.locator(".dropzone-file")).to_have_count(3)
    expect(inside.locator(".dropzone-file-name")).to_have_text(
        ["bild-1.png", "bild-2.png", "bild-3.png"]
    )
    expect(inside.locator(".dropzone-more")).to_have_text("+2 more files")
    expect(inside.locator("#selection")).to_contain_text("5 files")

    # Changing locale should preserve selection and retranslate the overflow.
    page.evaluate("window.MLXI18n.setLanguage('de')")
    expect(inside.locator(".dropzone-more")).to_have_text("+2 weitere Dateien")
    assert inside.locator("#imageFiles").evaluate("element => element.files.length") == 5

    inside.locator("#imageFiles").set_input_files([])
    expect(drop).not_to_have_class("has-files")
    expect(inside.locator("#dropzoneEmpty")).to_be_visible()
    expect(inside.locator(".dropzone-file")).to_have_count(0)
