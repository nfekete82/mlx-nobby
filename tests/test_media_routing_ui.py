import json

from backend.media_routing_ui import (
    MEDIA_ROUTING_SCRIPT,
    conservative_media_target,
    guard_media_route_payload,
    inject_media_routing_script,
)


def test_media_routing_script_is_injected_once():
    body = b"<html><body><main>chat</main></body></html>"

    injected = inject_media_routing_script(body)

    assert MEDIA_ROUTING_SCRIPT in injected
    assert injected.count(MEDIA_ROUTING_SCRIPT) == 1
    assert inject_media_routing_script(injected) == injected


def test_media_routing_script_requires_body_marker():
    body = b"plain response"

    assert inject_media_routing_script(body) == body


def test_short_semantic_image_prompt_requires_execution():
    assert conservative_media_target(
        "Eine Katze im Astronautenanzug auf dem Mond",
        "image",
    ) == "chat"


def test_long_normal_prose_is_demoted_to_chat():
    prompt = (
        "Ich habe hier einen längeren Text und möchte, dass du ihn analysierst. "
        "Darin kommen unter anderem die Wörter Bild, Foto und Illustration vor, "
        "aber ich möchte ausdrücklich nur eine inhaltliche Antwort. "
    ) * 8

    assert conservative_media_target(prompt, "image") == "chat"


def test_long_explicit_image_request_stays_image():
    prompt = (
        "Erstelle mir bitte ein Bild von einer futuristischen Stadt bei Nacht. "
        "Die Szene soll sehr detailliert sein und viele kleine Beschreibungen enthalten. "
    ) * 8

    assert conservative_media_target(prompt, "image") == "image"


def test_long_visual_prompt_without_command_requires_execution():
    prompt = (
        "Cinematic portrait, photorealistic, studio lighting, 85mm lens, bokeh, "
        "highly detailed skin, shallow depth of field, dramatic composition. "
    ) * 8

    assert conservative_media_target(prompt, "image") == "chat"


def test_long_normal_prose_is_not_routed_to_shorts():
    prompt = (
        "Analysiere bitte diesen langen Text. Darin geht es unter anderem um "
        "YouTube Shorts, TikTok und Reels als Plattformformate, aber ich möchte "
        "nur eine textliche Einschätzung. "
    ) * 8

    assert conservative_media_target(prompt, "shorts_generate") == "chat"


def test_ambiguous_short_mention_requires_explicit_creation_request():
    assert conservative_media_target(
        "Was hältst du von YouTube Shorts und Reels?",
        "shorts_generate",
    ) == "chat"


def test_explicit_shorts_request_keeps_router_decision():
    assert conservative_media_target(
        "Erstelle mir ein YouTube Short über Apple Silicon mit drei Szenen.",
        "shorts_generate",
    ) == "shorts_generate"


def test_explicit_english_shorts_request_keeps_router_decision():
    assert conservative_media_target(
        "Turn this into a 30 second TikTok video with captions.",
        "shorts_generate",
    ) == "shorts_generate"


def test_long_shorts_request_at_end_keeps_router_decision():
    prompt = (
        "Hier ist mein langer Ausgangstext über Apple Silicon und lokale KI. " * 20
        + "Mach daraus bitte ein Short mit drei Szenen und Untertiteln."
    )

    assert conservative_media_target(prompt, "shorts_generate") == "shorts_generate"


def test_unrelated_targets_are_never_changed():
    long_prompt = "normaler Text " * 100

    assert conservative_media_target(long_prompt, "image_edit") == "chat"
    assert conservative_media_target(long_prompt, "video") == "chat"
    assert conservative_media_target(long_prompt, "chat") == "chat"


def test_guard_rewrites_only_target_and_marks_reason():
    prompt = "Analysiere bitte diesen langen Text. " * 30
    request = json.dumps({"prompt": prompt}).encode()
    response = json.dumps({"target": "image", "confidence": 0.61}).encode()

    guarded = json.loads(guard_media_route_payload(request, response))

    assert guarded["target"] == "chat"
    assert guarded["confidence"] == 1.0
    assert guarded["routing_guard"] == "execution_required"


def test_shorts_guard_rewrites_target_and_marks_reason():
    prompt = "Analysiere diesen Text über Shorts und Reels. " * 30
    request = json.dumps({"prompt": prompt}).encode()
    response = json.dumps({"target": "shorts_generate", "confidence": 0.73}).encode()

    guarded = json.loads(guard_media_route_payload(request, response))

    assert guarded["target"] == "chat"
    assert guarded["confidence"] == 1.0
    assert guarded["routing_guard"] == "text_request_priority"


def test_guard_leaves_invalid_json_untouched():
    response = b'{"target":"image"}'

    assert guard_media_route_payload(b"not-json", response) == response
