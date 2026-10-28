"""Explicit generation-model selections must survive agent and image-service routing."""
from unittest.mock import Mock

from agent import app as agent
import image_service


def test_image_service_never_uses_qwen_auto_router_for_manually_chosen_ragnarok(monkeypatch):
    model = {"id": "juggernaut-xl", "provider": "sdxl", "enabled": True}
    get_model = Mock(return_value=model)
    monkeypatch.setattr(image_service.registry, "get_model", get_model)

    def forbidden_auto_route(_prompt):
        raise AssertionError("Automatic Qwen routing must not run for a manual model")

    monkeypatch.setattr(image_service, "_auto_generation_model", forbidden_auto_route)
    assert image_service._generation_model(
        "juggernaut-xl", "photorealistic portrait of a woman"
    ) == model
    get_model.assert_called_once_with("juggernaut-xl")


def test_agent_enqueues_exactly_the_explicit_user_model(monkeypatch):
    monkeypatch.setattr(agent, "translate_image_prompt_to_english", lambda _: "a photorealistic portrait")
    monkeypatch.setattr(agent, "_validated_image_job_chat_identity", lambda _request: ("chat-test", 0))

    def reject_auto_role(*_args, **_kwargs):
        raise AssertionError("Image role/Auto must not override a manually selected model")

    monkeypatch.setattr(agent, "validated_image_role", reject_auto_role)
    sent = []

    def fake_image_request(method, path, payload, **_kwargs):
        sent.append((method, path, payload))
        return {"id": "a" * 24, "status": "queued"}

    monkeypatch.setattr(agent.image_api, "request", fake_image_request)
    request = agent.ChatActionRequest(
        prompt="Bitte erstelle ein Bild von einer Frau",
        image_options={"model": "juggernaut-xl", "auto_size": True},
        chat_id="chat-test", chat_revision=0,
    )
    agent._start_chat_image_job("image_generate", request)
    assert sent[0][0:2] == ("POST", "/jobs")
    assert sent[0][2]["payload"]["model"] == "juggernaut-xl"
