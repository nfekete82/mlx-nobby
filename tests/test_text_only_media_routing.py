"""Regressions for text-only image edits and video command routing."""
from unittest.mock import patch

import pytest
from agent import app
from backend.media_intent import decide_media_intent

IMAGE = {"kind": "image", "mime_type": "image/png", "stored_path": "/tmp/current-image.png"}


@pytest.mark.parametrize("prompt", [
    "erstelle ein video: A confident 25-year-old woman dancing on a sunlit street at golden hour.",
    "Erstelle ein Video: eine erwachsene Frau tanzt im Sonnenlicht.",
    "Create a video: cinematic golden-hour street dancing.",
])
def test_text_only_video_uses_video_job_even_with_stale_chat_preflight(prompt):
    request = app.ChatActionRequest(
        prompt=prompt,
        resolved_target="chat",
        action="image_edit",  # a stale browser mode must not authorize editing
    )
    decision = app.preflight_chat_action(request)
    assert decision["intent"] == "video_generate"
    assert decision["target"] == "video"
    with (patch.object(app, "_start_chat_video_job", return_value={
            "id": "b" * 24, "status": "queued",
          }) as video,
          patch.object(app, "_start_chat_image_job") as image):
        result = app.run_chat_action(request)
    assert result["tool"] == "video_generate"
    assert result["data"]["routing"]["target"] == "video"
    video.assert_called_once()
    image.assert_not_called()


@pytest.mark.parametrize("action", ["image_edit", "image_reference_generate", "image_upscale"])
@pytest.mark.parametrize("prompt", [
    "Bearbeite das Bild",
    "Mach ihre Haare rot",
    "Ändere den Hintergrund",
])
def test_text_only_stale_edit_action_cannot_start_image_job(prompt, action):
    decision = decide_media_intent(prompt, has_image=False, action=action)
    assert decision.target == "chat"
    assert not decision.execution_requested
    assert decision.guard == "image_source_required"
    request = app.ChatActionRequest(prompt=prompt, action=action,
                                    resolved_target="image_edit")
    route = app.preflight_chat_action(request)
    assert route["target"] == "chat"
    with patch.object(app, "_start_chat_image_job") as image:
        result = app.run_chat_action(request)
    assert result["tool"] == "normal_chat"
    image.assert_not_called()


def test_freshly_attached_image_can_still_be_edited():
    request = app.ChatActionRequest(
        prompt="Bearbeite das Bild: mache den Himmel heller",
        action="image_edit", resolved_target="image_edit",
        file_context=IMAGE,
    )
    assert app.preflight_chat_action(request)["target"] == "image_edit"
    with patch.object(app, "_start_chat_image_job",
                      return_value={"id": "a" * 24, "status": "queued"}) as image:
        result = app.run_chat_action(request)
    assert result["tool"] == "image_edit"
    image.assert_called_once()


def test_video_prompt_never_becomes_image_edit_due_to_previous_image():
    prompt = "erstelle ein video: A cinematic scene in golden-hour sunlight."
    decision = decide_media_intent(prompt, has_image=False, action="image_edit")
    assert decision.intent == "video_generate"
    assert decision.target == "video"
