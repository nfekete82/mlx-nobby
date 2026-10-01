import json
from pathlib import Path

from backend import media_routing_portrait_intent as portrait_runtime
from backend import media_routing_ui


ROOT = Path(__file__).resolve().parents[1]


def test_portrait_generation_intent_matches_common_creation_prompts():
    assert portrait_runtime.is_explicit_portrait_generation(
        "Erstelle ein fotorealistisches Porträt einer Frau bei natürlichem Fensterlicht."
    )
    assert portrait_runtime.is_explicit_portrait_generation(
        "Create a photorealistic portrait of a woman in natural window light."
    )
    assert portrait_runtime.is_explicit_portrait_generation(
        "Generiere einen Headshot mit weichem Studiolicht."
    )
    assert portrait_runtime.is_explicit_portrait_generation(
        "Porträt von einer Frau bei Sonnenuntergang."
    )
    assert not portrait_runtime.is_explicit_portrait_generation(
        "Wie findest du dieses Porträt?"
    )


def test_portrait_request_survives_web_confidence_guard():
    portrait_runtime.install_runtime()
    prompt = (
        "Erstelle ein fotorealistisches Porträt einer Frau "
        "bei natürlichem Fensterlicht."
    )
    request = json.dumps({"prompt": prompt}).encode("utf-8")
    response = json.dumps({"target": "image"}).encode("utf-8")

    guarded = json.loads(
        media_routing_ui.guard_media_route_payload(request, response)
    )

    assert guarded["target"] == "image"
    assert "routing_guard" not in guarded
    observatory = guarded["routing_observatory"]
    assert observatory["original_target"] == "image"
    assert observatory["target"] == "image"
    assert observatory["confidence"] == 0.98
    assert observatory["confidence_source"] == "heuristic"
    assert observatory["guarded"] is False


def test_plain_portrait_discussion_is_not_promoted_to_explicit_image_intent():
    portrait_runtime.install_runtime()
    prompt = "Wie findest du dieses Porträt?"

    assert not media_routing_ui._explicit_intent(prompt, "image")


def test_production_backend_installs_portrait_guard_before_requests():
    source = (ROOT / "backend" / "entrypoint.py").read_text(encoding="utf-8")

    assert "install_media_routing_portrait_intent_runtime()" in source
