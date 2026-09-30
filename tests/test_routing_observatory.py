import json

import pytest
from fastapi import HTTPException

from backend import media_routing_ui as routing


def _route(prompt, target, confidence=None, action=None):
    request_payload = {"prompt": prompt}
    if action is not None:
        request_payload["action"] = action

    response_payload = {"target": target}
    if confidence is not None:
        response_payload["confidence"] = confidence

    return json.loads(
        routing.guard_media_route_payload(
            json.dumps(request_payload).encode(),
            json.dumps(response_payload).encode(),
        )
    )


def test_low_confidence_media_route_falls_back_to_chat():
    routed = _route("Eine Katze auf dem Mond", "image", 0.54)

    assert routed["target"] == "chat"
    assert routed["routing_guard"] == "low_confidence_fallback"
    assert routed["routing_observatory"]["confidence"] == 0.54
    assert routed["routing_observatory"]["guarded"] is True


def test_medium_confidence_requires_explicit_intent():
    routed = _route("Eine Katze auf dem Mond", "image", 0.78)

    assert routed["target"] == "chat"
    assert routed["routing_guard"] == "medium_confidence_requires_explicit_intent"


def test_medium_confidence_explicit_image_request_is_allowed():
    routed = _route("Erstelle ein Bild von einer Katze auf dem Mond.", "image", 0.78)

    assert routed["target"] == "image"
    assert "routing_guard" not in routed
    assert routed["routing_observatory"]["reason"] == "medium_confidence_explicit_intent"


def test_high_confidence_media_route_is_allowed_without_command():
    routed = _route("Eine Katze auf dem Mond", "image", 0.95)

    assert routed["target"] == "image"
    assert routed["routing_observatory"]["reason"] == "high_confidence"


def test_explicit_action_without_router_confidence_gets_full_confidence():
    routed = _route(
        "Eine Katze auf dem Mond",
        "image",
        action="image_generate",
    )

    assert routed["target"] == "image"
    assert routed["routing_observatory"]["confidence"] == 1.0
    assert routed["routing_observatory"]["confidence_source"] == "heuristic"


def test_long_chat_guard_wins_even_with_high_router_confidence():
    prompt = "Analysiere bitte diesen längeren Text über Bilder und Fotografie. " * 30
    routed = _route(prompt, "image", 0.99)

    assert routed["target"] == "chat"
    assert routed["routing_guard"] == "long_form_chat_fallback"


def test_routing_store_retains_preview_hash_and_feedback(tmp_path, monkeypatch):
    store = tmp_path / "routing-observatory.json"
    monkeypatch.setattr(routing, "ROUTING_OBSERVATORY_FILE", store)

    prompt = "Analysiere diesen Text, aber starte bitte keine Bildgenerierung."
    decision = routing.record_routing_decision({
        "prompt_preview": routing._normalized_prompt_preview(prompt),
        "prompt_sha256": routing.hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_chars": len(prompt),
        "original_target": "image",
        "target": "chat",
        "confidence": 0.72,
        "reason": "medium_confidence_requires_explicit_intent",
        "guarded": True,
    })

    decisions = routing.list_routing_decisions(20)
    assert len(decisions) == 1
    assert decisions[0]["id"] == decision["id"]
    assert decisions[0]["prompt_preview"] == prompt
    assert decisions[0]["prompt_sha256"] == routing.hashlib.sha256(prompt.encode()).hexdigest()
    assert "prompt" not in decisions[0]

    updated = routing.save_routing_feedback(decision["id"], False, "chat")
    assert updated["feedback"]["correct"] is False
    assert updated["feedback"]["expected_target"] == "chat"
    assert updated["regression_candidate"] is True
    assert routing.list_regression_candidates()[0]["id"] == decision["id"]


def test_routing_store_caps_retention(tmp_path, monkeypatch):
    store = tmp_path / "routing-observatory.json"
    monkeypatch.setattr(routing, "ROUTING_OBSERVATORY_FILE", store)
    monkeypatch.setattr(routing, "ROUTING_DECISION_LIMIT", 3)

    for index in range(5):
        routing.record_routing_decision({
            "id": str(index),
            "prompt_preview": str(index),
            "target": "chat",
        })

    decisions = routing.list_routing_decisions(20)
    assert [item["id"] for item in decisions] == ["4", "3", "2"]


def test_invalid_feedback_target_is_rejected(tmp_path, monkeypatch):
    store = tmp_path / "routing-observatory.json"
    monkeypatch.setattr(routing, "ROUTING_OBSERVATORY_FILE", store)

    decision = routing.record_routing_decision({
        "prompt_preview": "x",
        "target": "chat",
    })

    with pytest.raises(HTTPException) as exc:
        routing.save_routing_feedback(decision["id"], False, "unknown")

    assert exc.value.status_code == 400
