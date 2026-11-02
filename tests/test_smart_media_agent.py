"""Smart Media v1: Qwen plans prompts, while existing job routing stays in charge."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent import app
from agent import media_copilot
from agent.model_provider import ModelResponse


MODELS = [
    {"id": "juggernaut-xl", "name": "Juggernaut XL",
     "enabled": True, "capabilities": ["text_to_image"]},
    {"id": "mlxserve-qwen-image-2.1", "name": "Qwen Image 2.1",
     "enabled": True, "capabilities": ["text_to_image"]},
    {"id": "mflux-osaurus-qwen-image-2.1-edit", "name": "Qwen Image Edit",
     "enabled": True, "capabilities": ["image_edit"]},
    {"id": "disabled-test-model", "name": "Disabled",
     "enabled": False, "capabilities": ["text_to_image", "image_edit"]},
]


def complete_json(prompt="An adult woman cycling in morning sunlight.",
                  model="juggernaut-xl", negative="blur"):
    def complete(_messages):
        return json.dumps({"prompt": prompt, "model": model, "negative_prompt": negative})
    return complete


def test_smart_image_selects_only_enabled_model_and_prompt():
    result = media_copilot.plan_media(
        prompt="Erstelle mir ein Bild von einer blonden Frau auf dem Fahrrad.",
        target="image", source_kind="none", candidate_models=MODELS,
        complete=complete_json(),
    )
    assert result["mode"] == "smart"
    assert result["target"] == "image"
    assert result["model"] == "juggernaut-xl"
    assert result["negative_prompt"] == "blur"
    assert result["prompt"] == "An adult woman cycling in morning sunlight."


def test_manual_image_model_overrides_qwen_and_unsupported_negative_prompt():
    result = media_copilot.plan_media(
        prompt="Create an image of a bicycle.", target="image",
        source_kind="none", candidate_models=MODELS,
        selected_model="mlxserve-qwen-image-2.1",
        complete=complete_json(model="juggernaut-xl"),
    )
    assert result["model"] == "mlxserve-qwen-image-2.1"
    assert result["negative_prompt"] == ""


def test_edit_and_video_keep_preset_target_and_no_negative_prompt():
    for target, candidates, selected in (
        ("image_edit", MODELS, "auto"),
        ("video", [], "auto"),
    ):
        result = media_copilot.plan_media(
            prompt="Ändere das Bild: natural skin, not a model.",
            target=target, source_kind="image", candidate_models=candidates,
            selected_model=selected, complete=complete_json(
                prompt="Natural skin, not a model; retain appearance.",
                model="mflux-osaurus-qwen-image-2.1-edit",
                negative="bad hands",
            ),
        )
        assert result["target"] == target
        assert "not a model" in result["prompt"]
        assert result["negative_prompt"] == ""
        if target == "video":
            assert result["model"] == "auto"


def test_invalid_llm_response_is_direct_fallback_without_model_switch():
    for answer in ("not json", "{}", '{"prompt": "", "model": "auto"}'):
        result = media_copilot.plan_media(
            prompt="Erstelle ein Bild", target="image",
            source_kind="none", candidate_models=MODELS,
            selected_model="juggernaut-xl", complete=lambda _: answer,
        )
        assert result["mode"] == "direct"
        assert result["model"] == "juggernaut-xl"
        assert result["prompt"] == "Erstelle ein Bild"


def test_disabled_manual_model_not_silently_substituted():
    result = media_copilot.plan_media(
        prompt="Generate photo", target="image", source_kind="none",
        selected_model="disabled-test-model", candidate_models=MODELS,
        complete=lambda _: (_ for _ in ()).throw(AssertionError("No LLM")),
    )
    assert result["mode"] == "direct"
    assert result["model"] == "disabled-test-model"


def test_invalid_qwen_model_selection_downgrades_to_auto_not_arbitrary_id():
    result = media_copilot.plan_media(
        prompt="A bicycle", target="image", source_kind="none",
        candidate_models=MODELS,
        complete=complete_json(model="../../untrusted-model"),
    )
    assert result["mode"] == "smart"
    assert result["model"] == "auto"


def test_web_media_planner_endpoint_uses_chat_role_and_only_enabled_models(monkeypatch):
    class FakeModelProvider:
        def complete(self, request, *, run_context=None):
            assert request.role == "chat"
            assert request.max_tokens == 850
            body = json.loads(request.messages[-1]["content"])
            assert body["authorized_target"] == "image"
            assert body["selected_model"] == "auto"
            assert "disabled-test-model" not in [m["id"] for m in body["available_models"]]
            return ModelResponse(
                text=json.dumps({
                    "prompt": "Photo of a woman cycling along a river.",
                    "model": "juggernaut-xl", "negative_prompt": "noise",
                }),
                model="chat", role="chat", usage={},
            )

    monkeypatch.setattr(app, "agent_model_provider", lambda: FakeModelProvider())
    with patch("image_registry.load_registry", return_value={"models": MODELS}):
        client = TestClient(app.app, base_url="http://localhost")
        result = client.post("/api/chat/media/plan", json={
            "prompt": "Erstelle eine blonde Frau auf einem Fahrrad.",
            "target": "image", "selected_model": "auto", "source_kind": "none",
        })
    assert result.status_code == 200
    assert result.json()["prompt"].startswith("Photo of a woman")
    assert result.json()["model"] == "juggernaut-xl"
    assert result.json()["mode"] == "smart"


def test_planning_endpoint_rejects_unauthorized_operation(monkeypatch):
    client = TestClient(app.app, base_url="http://localhost")
    resp = client.post("/api/chat/media/plan", json={
        "prompt": "Write a file", "target": "shell_exec",
    })
    assert resp.status_code == 422


def test_existing_image_router_independent_of_qwen_planner():
    from backend.media_intent import decide_media_intent
    assert decide_media_intent(
        "Ändere das Bild: not a model", has_image=True
    ).target == "image_edit"
    assert decide_media_intent(
        "Erstelle ein Bild von einer Frau auf einem Fahrrad", has_image=False
    ).target == "image"



def test_compiled_image_prompt_skips_translation_and_preserves_original(monkeypatch):
    def unexpected_translation(_prompt):
        raise AssertionError("Smart Media prompt was translated twice")
    monkeypatch.setattr(app, "translate_image_prompt_to_english", unexpected_translation)
    request = app.ChatActionRequest(
        prompt="Erstelle ein Bild von einer Frau auf einem Fahrrad",
        image_options={
            "model": "juggernaut-xl",
            "prompt": "Photorealistic cyclist with natural lighting.",
        },
    )
    payload = app._image_generate_payload(request)
    assert payload["prompt"] == "Photorealistic cyclist with natural lighting."
    assert payload["original_prompt"] == request.prompt
    assert payload["model"] == "juggernaut-xl"


def test_compiled_t2v_prompt_skips_translation_and_retains_duration(monkeypatch):
    def unexpected_translation(_prompt):
        raise AssertionError("Smart Media video prompt was translated twice")
    monkeypatch.setattr(app, "compile_video_prompt", unexpected_translation)
    request = app.ChatActionRequest(
        prompt="Erstelle ein Video von einer Fahrradfahrt.",
        video_options={
            "prompt": "A person cycling slowly; locked-off camera.",
            "duration": 5,
            "profile": "standard",
        },
    )
    payload = app._video_payload(request, "t2v")
    assert payload["prompt"] == "A person cycling slowly; locked-off camera."
    assert payload["duration"] == 5
    assert payload["profile"] == "standard"
