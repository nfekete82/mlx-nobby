"""The same contract holds at preflight, execution and web middleware."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from agent import app, run_state, runtime_tools
from backend.media_intent import MEDIA_ACTIONS, decide_media_intent
from backend.media_routing_ui import guard_media_route_payload

IMAGE = {"kind": "image", "mime_type": "image/png", "stored_path": "/tmp/context.png"}
MATRIX = [
    ("beschreibe sie", True, "chat"),
    ("welcher Prompt ist gut für LTX?", True, "chat"),
    ("erstelle mir einen Prompt für LTX 2.5", True, "chat"),
    ("erstelle mir einen sexy Prompt für LTX", True, "chat"),
    ("erstelle mir einen prompt für ltx 2.5 wie sie sexy schaut, einen kussmund macht und sich bewegt", True, "chat"),
    ("animiere dieses Bild mit LTX", True, "video"),
    ("erstelle daraus ein Video", True, "video"),
    ("bearbeite ihr Lächeln", True, "image_edit"),
    ("erstelle ein neues Bild von ihr", True, "image"),
    ("erstelle einen Prompt für ein Bild", False, "chat"),
    ("erstelle ein Bild", False, "image"),
    ("schreib mir ein Short-Skript", False, "chat"),
    ("erstelle daraus ein Short", False, "shorts_generate"),
    ("was hältst du von Porträtfotografie?", False, "chat"),
    ("mach ein Porträt", False, "image"),
    ("Describe her", True, "chat"),
    ("Which prompt is best for LTX?", True, "chat"),
    ("Create a sexy LTX prompt", True, "chat"),
    ("Write an image prompt", False, "chat"),
    ("Improve this prompt", True, "chat"),
    ("What should I write to LTX?", True, "chat"),
    ("Animate this image with LTX", True, "video"),
    ("Create a video from this", True, "video"),
    ("Edit her smile", True, "image_edit"),
    ("Make her hair red", True, "image_edit"),
    ("Create a new image of her", True, "image"),
    ("Write a script for a Short", False, "chat"),
    ("Create a Short", False, "shorts_generate"),
    ("What do you think about portrait photography?", False, "chat"),
    ("Make a portrait", False, "image"),
    ("starte LTX", False, "video"),
    ("sexy nude portrait", True, "chat"),
    ("Bild von ihr", True, "chat"),
    ("mach sie nicht so dunkel", True, "image_edit"),
    ("mach das Bild nicht so warm", True, "image_edit"),
    ("mach ihre Haare nicht so hell", True, "image_edit"),
    ("make her hair not so dark", True, "image_edit"),
    ("make the background not so bright", True, "image_edit"),
    ("mach ihre Haare nicht heller", True, "image_edit"),
    ("edit the background not too bright", True, "image_edit"),
    ("mach das Bild nicht dunkel", True, "image_edit"),
    ("mach das Bild nicht", True, "chat"),
    ("bearbeite das Bild nicht", True, "chat"),
    ("edit not the background", True, "chat"),
    ("don't edit this image", True, "chat"),
    ("mach nicht das Bild dunkel", True, "chat"),
    ("erstelle einen Prompt für ein Bild nicht so dunkel", True, "chat"),
    ("write a prompt for hair not so dark", True, "chat"),
    ("Do not generate an image", True, "chat"),
    ('Explain "generate an image"', True, "chat"),
    ("generiere mir einen Prompt für ein Bild", True, "chat"),
    ("Create an image prompt for a video", True, "chat"),
    ("erstelle ein Short-Skript", True, "chat"),
    ("Wie kann ich ein Video generieren?", True, "chat"),
    ("Optimiere den Prompt und generiere danach das Bild", True, "image"),
    ("Für dieses Bild erstelle einen Prompt für LTX", True, "chat"),
    ("For this image create a prompt for LTX", True, "chat"),
    ("Use this prompt to generate an image", False, "image"),
    ("bitte ganzkörper", True, "image_edit"),
    ("und jetzt etwas wärmer", True, "image_edit"),
]


@pytest.mark.parametrize("prompt,has_image,target", MATRIX)
def test_matrix_across_real_endpoints(prompt, has_image, target):
    client = TestClient(app.app, base_url="http://localhost")
    payload = {"prompt": prompt}
    if has_image:
        payload["file_context"] = IMAGE
    with patch.object(app, "semantic_intent_classifier", return_value={
        "intent": "image_generate", "confidence": .99, "requires_tools": True,
    }), patch.object(app, "_start_chat_image_job", return_value={"id": "a" * 24, "status": "queued"}) as image, \
         patch.object(app, "_start_chat_video_job", return_value={"id": "b" * 24, "status": "queued"}) as video, \
         patch.object(app, "_start_chat_shorts_job", return_value={"id": "c" * 24, "status": "queued"}) as shorts:
        route = client.post("/api/chat/actions/route", json=payload)
        assert route.status_code == 200
        decision = route.json()
        assert decision["target"] == target
        assert decision["execution_requested"] == (target != "chat")
        assert not image.called and not video.called and not shorts.called
        guarded = json.loads(guard_media_route_payload(json.dumps(payload).encode(), route.content))
        assert guarded["target"] == target
        result = client.post("/api/chat/actions", json=payload)
        assert result.status_code == 200
        assert image.called == (target in {"image", "image_edit"})
        assert video.called == (target == "video")
        assert shorts.called == (target == "shorts_generate")
        assert result.json()["data"]["routing"]["target"] == target
        if target == "chat":
            assert result.json()["tool"] == "normal_chat"


@pytest.mark.parametrize("action", MEDIA_ACTIONS)
@pytest.mark.parametrize("binding", [{"file_context": IMAGE}, {"active_artifact_id": "image-test"}])
def test_stale_targets_and_explicit_actions_cannot_override_prompt_request(action, binding):
    payload = {"prompt": "erstelle mir einen sexy Prompt für LTX 2.5", **binding,
               "resolved_target": "image"}
    if action != "shorts_generate":
        payload["action"] = action
    with patch.object(app, "_start_chat_image_job") as image, patch.object(app, "_start_chat_video_job") as video, patch.object(app, "_start_chat_shorts_job") as shorts:
        result = TestClient(app.app, base_url="http://localhost").post("/api/chat/actions", json=payload)
        assert result.status_code == 200
        assert result.json()["tool"] == "normal_chat"
        assert not image.called and not video.called and not shorts.called


@pytest.mark.parametrize("action", MEDIA_ACTIONS)
def test_model_tool_query_cannot_turn_user_prompt_request_into_execution(action):
    context = run_state.RunContext.start(workspace_bound=True)
    with run_state.bind_run_context(context), pytest.raises(ValueError, match="MEDIA_EXECUTION_NOT_REQUESTED"):
        runtime_tools.execute(action, goal="Write a prompt for LTX", query="Generate a video")


def test_observability_never_persists_prompt_or_attachment(tmp_path, monkeypatch):
    from backend import media_routing_ui as routing
    store = tmp_path / "routing.json"
    monkeypatch.setattr(routing, "ROUTING_OBSERVATORY_FILE", store)
    request = {"prompt": "Describe Alice PrivateName", "file_context": {**IMAGE, "base64": "SECRET_IMAGE_BYTES"}}
    guard_media_route_payload(json.dumps(request).encode(), b'{"target":"image","confidence":0.99}', record=True)
    saved = store.read_text()
    assert "Alice" not in saved and "PrivateName" not in saved and "SECRET_IMAGE_BYTES" not in saved
    decision = json.loads(saved)["decisions"][0]
    assert decision["intent"] == "vision_chat" or decision["intent"] == "discussion"
    assert decision["execution_requested"] is False


def test_browser_chat_fallback_cannot_be_promoted_at_execution():
    with patch.object(app, "_start_chat_image_job") as image:
        result = app.run_chat_action(app.ChatActionRequest(prompt="Create an image", resolved_target="chat"))
        assert result["tool"] == "normal_chat"
        image.assert_not_called()


@pytest.mark.parametrize("action", MEDIA_ACTIONS)
def test_delegated_goal_cannot_override_original_user_goal(action):
    context = run_state.RunContext.start(workspace_bound=True, user_goal="Write a prompt for LTX")
    with run_state.bind_run_context(context), pytest.raises(ValueError, match="MEDIA_EXECUTION_NOT_REQUESTED"):
        runtime_tools.execute(action, goal="Generate a video", query="Generate a video")


@pytest.mark.parametrize("context", [{"stored_path": "/tmp/reference.png"}, {"mime": "image/jpeg"}, {"type": "image/webp"}])
def test_attachment_metadata_uses_same_context_policy_in_agent_and_web(context):
    request = {"prompt": "Edit her smile", "file_context": context}
    route = app.preflight_chat_action(app.ChatActionRequest(**request))
    guarded = json.loads(guard_media_route_payload(json.dumps(request).encode(), json.dumps(route).encode()))
    assert route["target"] == guarded["target"] == "image_edit"


@pytest.mark.parametrize("prompt", [
    "generiere kein Bild", "do not generate an image",
    "erstelle kein Video", "don't animate this image",
    "generiere niemals ein Bild", "never animate this image",
])
@pytest.mark.parametrize("has_image", [False, True])
def test_execution_negation_blocks_preflight_and_stale_media_action(prompt, has_image):
    test_matrix_across_real_endpoints(prompt, has_image, "chat")
    # A client hint or explicit UI action must not override withheld execution.
    request = app.ChatActionRequest(
        prompt=prompt, file_context=IMAGE if has_image else None,
        action="image_generate", resolved_target="image",
    )
    with patch.object(app, "_start_chat_image_job") as image, patch.object(app, "_start_chat_video_job") as video:
        result = app.run_chat_action(request)
    assert result["tool"] == "normal_chat"
    assert result["data"]["routing"]["execution_requested"] is False
    image.assert_not_called()
    video.assert_not_called()
