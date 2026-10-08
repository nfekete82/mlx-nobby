"""Talking Photo progress/recovery through the actual browser module and mocked local API."""
import io
import json
import re
import time

from PIL import Image
from playwright.sync_api import expect


def test_talking_photo_progress_reopen_and_cancel(ui):
    page, _agent, _allowed = ui
    job_id = "a" * 24
    now = time.time() - 20
    job = {
        "id": job_id, "kind": "talking_photo", "status": "queued",
        "phase": "queued", "progress": 0.0, "created_at": now,
        "started_at": None, "cancel_requested": False, "error": None,
    }
    requests = {"create": 0, "poll": 0, "cancel": 0}

    def respond(route, payload, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(payload))

    def create(route):
        requests["create"] += 1
        body = route.request.post_data_json
        assert body["engine"] == "ltx"
        respond(route, dict(job), 202)

    def poll(route):
        requests["poll"] += 1
        respond(route, dict(job))

    def cancel(route):
        requests["cancel"] += 1
        job.update(cancel_requested=True)
        respond(route, dict(job))

    page.route("**/api/talking-photo/status",
               lambda route: respond(route, {"providers": {"ltx": {"ready": True, "device": "mlx/metal"}}}))
    page.route("**/api/mlx/audio/voices/manage",
               lambda route: respond(route, {"voices": []}))
    page.route("**/api/talking-photo/jobs", create)
    page.route(f"**/api/talking-photo/jobs/{job_id}", poll)
    page.route(f"**/api/talking-photo/jobs/{job_id}/cancel", cancel)

    page.locator("#talkingPhotoButton").click()
    expect(page.locator("#talkingPhotoModal")).to_be_visible()
    png = io.BytesIO()
    Image.new("RGB", (32, 32), (30, 100, 150)).save(png, "PNG")
    page.locator("#talkingPhotoImage").set_input_files(
        {"name": "portrait.png", "mimeType": "image/png", "buffer": png.getvalue()}
    )
    page.locator("#talkingPhotoText").fill("Hello, this is a progress test.")
    page.locator("#talkingPhotoCreate").click()

    expect(page.locator("#talkingPhotoActivity")).to_be_visible()
    expect(page.locator("#talkingPhotoButton")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#talkingPhotoProgressTrack")).not_to_have_attribute("aria-valuenow", "0")
    expect(page.locator("#talkingPhotoCancel")).to_be_enabled()
    expect(page.locator("#talkingPhotoCreate")).to_be_disabled()
    assert requests["create"] == 1

    job.update(status="tts", phase="tts", started_at=time.time() - 8)
    expect(page.locator("#talkingPhotoActivityPhase")).to_contain_text(re.compile("Stimme|voice", re.I))
    job.update(status="motion", phase="quality", progress=0.42)
    expect(page.locator("#talkingPhotoProgressTrack")).to_have_attribute("aria-valuenow", "42")
    expect(page.locator("#talkingPhotoProgressLabel")).to_contain_text(re.compile("geschätzt|estimated", re.I))
    expect(page.locator("#talkingPhotoActivityPhase")).to_contain_text("LTX")
    # Time is shown and updates independently of the coarse server progress.
    expect(page.locator("#talkingPhotoElapsed")).to_contain_text(re.compile("Laufzeit:|Elapsed:", re.I))

    page.locator(".mlx-talking-photo-close").click()
    expect(page.locator("#talkingPhotoModal")).to_be_hidden()
    expect(page.locator("#talkingPhotoButton")).to_have_class(re.compile("is-generating"))
    count_before = requests["poll"]
    page.wait_for_timeout(1150)
    assert requests["poll"] > count_before

    page.locator("#talkingPhotoButton").click()
    expect(page.locator("#talkingPhotoProgressTrack")).to_have_attribute("aria-valuenow", "42")
    expect(page.locator("#talkingPhotoCancel")).to_be_enabled()
    assert requests["create"] == 1, "Reload must not start a duplicate generation"

    page.locator("#talkingPhotoCancel").click()
    expect(page.locator("#talkingPhotoCancel")).to_be_disabled()
    assert requests["cancel"] == 1
    job.update(status="cancelled", phase="cancelled", finished_at=time.time())
    expect(page.locator("#talkingPhotoButton")).to_have_attribute("aria-busy", "false")
    expect(page.locator("#talkingPhotoCancel")).to_be_hidden()
    expect(page.locator("#talkingPhotoCreate")).to_be_enabled()
    expect(page.locator("#talkingPhotoSpinner")).to_be_hidden()
    # A completed/cancelled session can still be inspected after a reload.
    page.reload()
    expect(page.locator("#talkingPhotoButton")).to_have_attribute("aria-busy", "false")
    assert requests["create"] == 1


def test_talking_photo_stale_session_recovers(ui):
    page, _agent, allowed = ui
    allowed.append("Failed to load resource: the server responded with a status of 404")
    job_id = "b" * 24
    page.route(f"**/api/talking-photo/jobs/{job_id}",
               lambda route: route.fulfill(status=404, content_type="application/json",
                                           body=json.dumps({"detail": "Job not found"})))
    page.route("**/api/talking-photo/status",
               lambda route: route.fulfill(status=200, content_type="application/json",
                                           body=json.dumps({"providers": {"ltx": {"ready": True}}})))
    page.route("**/api/mlx/audio/voices/manage",
               lambda route: route.fulfill(status=200, content_type="application/json",
                                           body=json.dumps({"voices": []})))
    page.evaluate("(id) => sessionStorage.setItem('mlxTalkingPhotoCurrentJob', id)", job_id)
    page.reload()
    expect(page.locator("#talkingPhotoButton")).to_have_attribute("aria-busy", "false")
    assert page.evaluate("sessionStorage.getItem('mlxTalkingPhotoCurrentJob')") is None
    page.locator("#talkingPhotoButton").click()
    expect(page.locator("#talkingPhotoCreate")).to_be_enabled()
