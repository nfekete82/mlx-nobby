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
    requests = {"create": 0, "poll": 0, "cancel": 0, "discard": 0}

    def respond(route, payload, status=200):
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(payload))

    def create(route):
        requests["create"] += 1
        body = route.request.post_data_json
        assert body["engine"] == "ltx"
        assert body["lead_in_ms"] == 500
        respond(route, dict(job), 202)

    def poll(route):
        requests["poll"] += 1
        respond(route, dict(job))

    def cancel(route):
        requests["cancel"] += 1
        job.update(cancel_requested=True)
        respond(route, dict(job))

    def discard(route):
        requests["discard"] += 1
        respond(route, dict(job))

    page.route("**/api/talking-photo/status",
               lambda route: respond(route, {"providers": {"ltx": {"ready": True, "device": "mlx/metal"}}}))
    page.route("**/api/mlx/audio/voices/manage",
               lambda route: respond(route, {"voices": []}))
    page.route("**/api/talking-photo/jobs", create)
    page.route(f"**/api/talking-photo/jobs/{job_id}", poll)
    page.route(f"**/api/talking-photo/jobs/{job_id}/cancel", cancel)
    page.route(f"**/api/talking-photo/jobs/{job_id}/discard", discard)

    page.locator("#talkingPhotoButton").click()
    expect(page.locator("#talkingPhotoModal")).to_be_visible()
    png = io.BytesIO()
    Image.new("RGB", (32, 32), (30, 100, 150)).save(png, "PNG")
    page.locator("#talkingPhotoImage").set_input_files(
        {"name": "portrait.png", "mimeType": "image/png", "buffer": png.getvalue()}
    )
    page.locator("#talkingPhotoText").fill("Hello, this is a progress test.")
    expect(page.locator("#talkingPhotoLeadIn")).to_have_value("0")
    page.locator("#talkingPhotoEngine").select_option("fast")
    expect(page.locator("#talkingPhotoLeadInField")).to_be_hidden()
    page.locator("#talkingPhotoEngine").select_option("ltx")
    expect(page.locator("#talkingPhotoLeadInField")).to_be_visible()
    page.locator("#talkingPhotoLeadIn").select_option("500")
    expect(page.locator("#talkingPhotoCreate")).to_be_enabled()
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
    assert requests["discard"] == 0, "Closing the dialog must not cancel active work"
    count_before = requests["poll"]
    page.wait_for_timeout(1150)
    assert requests["poll"] > count_before
    assert requests["discard"] == 0

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


def test_talking_photo_responsive_preview_and_finished_video_layout(ui):
    page, _agent, _allowed = ui
    page.locator("#talkingPhotoButton").click()
    expect(page.locator("#talkingPhotoModal")).to_be_visible()

    # A finished result is always owned by the third output panel, never
    # appended below the entire form as in the previous implementation.
    assert page.locator("#talkingPhotoResultFrame").evaluate(
        "(frame) => frame.contains(document.getElementById('talkingPhotoResult'))"
    )
    assert page.locator("#talkingPhotoOutput").evaluate(
        "(output) => output.contains(document.getElementById('talkingPhotoStatus'))"
            " && output.contains(document.getElementById('talkingPhotoActivity'))"
            " && output.contains(document.getElementById('talkingPhotoCreate'))"
            " && output.contains(document.getElementById('talkingPhotoDownload'))"
    )
    expect(page.locator("#talkingPhotoResultPlaceholder")).to_be_visible()
    expect(page.locator("#talkingPhotoResult")).to_be_hidden()
    geometry = page.evaluate("""() => {
        const bounds = selector => {
            const box = document.querySelector(selector).getBoundingClientRect();
            return {left: box.left, right: box.right, top: box.top,
                    bottom: box.bottom, width: box.width};
        };
        return {
            width: innerWidth, height: innerHeight,
            dialog: bounds('.mlx-talking-photo-dialog'),
            source: bounds('.mlx-talking-photo-source'),
            settings: bounds('.mlx-talking-photo-settings'),
            output: bounds('#talkingPhotoOutput'),
        };
    }""")
    assert geometry["dialog"]["right"] <= geometry["width"] + 2
    if geometry["width"] >= 1101:
        assert geometry["dialog"]["width"] > 1000
        assert geometry["source"]["right"] < geometry["settings"]["left"]
        assert geometry["settings"]["right"] < geometry["output"]["left"]
        assert geometry["output"]["right"] <= geometry["dialog"]["right"]
        assert abs(geometry["source"]["top"] - geometry["output"]["top"]) < 3
        assert geometry["dialog"]["bottom"] <= geometry["height"] + 2
    else:
        assert geometry["source"]["top"] < geometry["settings"]["top"]
        assert geometry["settings"]["bottom"] < geometry["output"]["top"]
        assert geometry["output"]["right"] <= geometry["dialog"]["right"]

    # Simulate reveal without a media fetch: the preview must fit the panel.
    page.evaluate("""() => {
        document.getElementById('talkingPhotoResultPlaceholder').hidden = true;
        document.getElementById('talkingPhotoResult').hidden = false;
    }""")
    expect(page.locator("#talkingPhotoResult")).to_be_visible()
    expect(page.locator("#talkingPhotoResultPlaceholder")).to_be_hidden()
    frame = page.locator("#talkingPhotoResultFrame").bounding_box()
    video = page.locator("#talkingPhotoResult").bounding_box()
    assert frame and video
    assert video["x"] >= frame["x"] - 2
    assert video["x"] + video["width"] <= frame["x"] + frame["width"] + 2
