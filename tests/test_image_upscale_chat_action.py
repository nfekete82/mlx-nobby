"""Regression for Enhance button/media router mismatch."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent import app as agent
from backend.media_intent import decide_media_intent

IMAGE = {"kind": "image", "mime_type": "image/png", "stored_path": "/tmp/fixture.png"}


@pytest.mark.parametrize("prompt", [
    "Bild verbessern",
    "Bild verbessern · 4× Photo",
    "Bild verbessern · 2× Photo",
    "Bild verbessern · 4× Illustration",
])
def test_explicit_enhance_button_routes_to_upscale(prompt):
    route = decide_media_intent(prompt, has_image=True, action="image_upscale")
    assert route.intent == "image_upscale"
    assert route.target == "image"
    assert route.execution_requested is True

    client = TestClient(agent.app, base_url="http://localhost")
    try:
        request = {
            "prompt": prompt,
            "action": "image_upscale",
            "file_context": IMAGE,
            "image_options": {"preset": "photo-4x"},
        }
        with patch.object(agent, "_start_chat_image_job",
                          return_value={"id": "a" * 24, "status": "queued"}) as create:
            preflight = client.post("/api/chat/actions/route", json=request)
            assert preflight.status_code == 200
            assert preflight.json()["intent"] == "image_upscale"
            result = client.post("/api/chat/actions", json=request)
        assert result.status_code == 200
        response = result.json()
        assert response["tool"] == "image_upscale"
        assert response["status"] == "queued"
        create.assert_called_once()
        assert create.call_args.args[0] == "image_upscale"
    finally:
        client.close()


@pytest.mark.parametrize("prompt, expected", [
    ("Färbe das Bild rot", "image_edit"),
    ("Verändere die Bildkomposition", "image_edit"),
    ("Bitte das Bild nicht verbessern", "discussion"),
    ("Erkläre wie Bildverbesserung funktioniert", "discussion"),
])
def test_upscale_button_never_overrides_different_instruction(prompt, expected):
    route = decide_media_intent(prompt, has_image=True, action="image_upscale")
    assert route.intent == expected


def test_image_description_without_button_does_not_launch_upscale():
    route = decide_media_intent("Beschreibe das Bild", has_image=True)
    assert not route.execution_requested
    assert route.intent != "image_upscale"


def test_upscale_action_alone_still_requires_actual_image_source():
    route = decide_media_intent("Bild verbessern", has_image=False, action="image_upscale")
    # A forged button action is never enough to fabricate a local image path.
    # The agent's _image_source_path remains the authority for job creation.
    assert route.intent != "image_edit"
