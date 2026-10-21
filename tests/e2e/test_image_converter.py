"""Real-browser converter smoke test against the production FastAPI entrypoint."""
from io import BytesIO
import zipfile

from PIL import Image
from playwright.sync_api import expect


def _png():
    data = BytesIO()
    Image.new("RGBA", (64, 40), (240, 30, 100, 125)).save(data, "PNG")
    return data.getvalue()


def test_converter_dropzone_upload_progress_and_zip_download(web, browser, tmp_path):
    url, agent = web
    agent.reset()
    context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(url + "/converter", wait_until="load", timeout=15000)
        expect(page.locator("#dropZone")).to_be_visible()
        expect(page.locator("#startButton")).to_be_disabled()
        page.locator("#filePicker").set_input_files(
            [{"name": "Testbild.png", "mimeType": "image/png", "buffer": _png()}]
        )
        expect(page.locator("#fileSummary")).to_contain_text("1 Dateien")
        expect(page.locator("#startButton")).to_be_enabled()
        page.locator("#target").select_option("jpg")
        page.locator("#startButton").click()
        expect(page.locator("#progressText")).to_contain_text("Fertig:", timeout=20000)
        expect(page.locator("#downloadAll")).to_be_visible()
        expect(page.locator(".result-row")).to_have_count(1)
        with page.expect_download(timeout=15000) as pending:
            page.locator("#downloadAll").click()
        download = pending.value
        assert download.suggested_filename == "mlx-nobby-bilder.zip"
        destination = tmp_path / "output.zip"
        download.save_as(destination)
        with zipfile.ZipFile(destination) as archive:
            assert "Testbild.jpg" in archive.namelist()
            assert "ergebnisse.json" in archive.namelist()
        assert not errors, errors
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert agent.count("/api/bridge/mlx", "POST") == 0
    finally:
        context.close()
