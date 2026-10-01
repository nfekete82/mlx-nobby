import json

from backend import media_routing_ui
from backend.media_prompt_meta_guard import (
    install_media_prompt_meta_guard,
    is_media_prompt_meta_request,
)


def _guard(prompt: str, *, target: str = "image", confidence: float = 0.99):
    request = json.dumps({"prompt": prompt}).encode()
    response = json.dumps({"target": target, "confidence": confidence}).encode()
    return json.loads(media_routing_ui.guard_media_route_payload(request, response))


def test_user_regression_prompt_for_juggernaut_is_meta_chat_request():
    assert is_media_prompt_meta_request(
        "mach mir mal einen prompt fertig für juggernaut damit ich sie erstelle in der pose so perfekt wie möglich"
    )


def test_user_ltx_prompt_request_with_reference_image_language_stays_chat():
    prompt = (
        "ich brauche den perfekten prompt für ltx 2.5 damit sie einen "
        "kussmund macht lächelt und den kopf leicht bewegt"
    )

    assert is_media_prompt_meta_request(prompt)

    install_media_prompt_meta_guard()
    guarded = _guard(
        prompt,
        target="video",
        confidence=0.99,
    )

    assert guarded["target"] == "chat"
    assert guarded["routing_guard"] == "media_prompt_meta_chat"
    assert guarded["routing_observatory"]["reason"] == "media_prompt_meta_chat"
    assert guarded["routing_observatory"]["guarded"] is True


def test_prompt_optimization_is_meta_chat_request():
    assert is_media_prompt_meta_request("Optimiere diesen Prompt bitte für Juggernaut XL.")
    assert is_media_prompt_meta_request("Welchen Prompt würdest du für SDXL verwenden?")
    assert is_media_prompt_meta_request("Write me a better image prompt for Flux.")


def test_explicit_generation_overrides_prompt_meta_language():
    assert not is_media_prompt_meta_request(
        "Optimiere diesen Prompt für Juggernaut und generiere danach das Bild."
    )
    assert not is_media_prompt_meta_request(
        "Nimm diesen Prompt und render das Bild jetzt."
    )


def test_high_confidence_image_router_is_demoted_for_prompt_writing():
    install_media_prompt_meta_guard()

    guarded = _guard(
        "mach mir mal einen prompt fertig für juggernaut damit ich sie erstelle in der pose so perfekt wie möglich",
        confidence=0.99,
    )

    assert guarded["target"] == "chat"
    assert guarded["routing_guard"] == "media_prompt_meta_chat"
    assert guarded["routing_observatory"]["reason"] == "media_prompt_meta_chat"
    assert guarded["routing_observatory"]["guarded"] is True


def test_explicit_generation_still_reaches_image_backend():
    install_media_prompt_meta_guard()

    guarded = _guard(
        "Optimiere den Prompt für Juggernaut und generiere danach das Bild.",
        confidence=0.99,
    )

    assert guarded["target"] == "image"
    assert guarded["routing_observatory"]["guarded"] is False
