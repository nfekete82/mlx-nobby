"""Contract tests for the shared chat decision and missing-slot handling."""
from unittest import mock

from fastapi.testclient import TestClient

from agent import app
from agent.chat_decision import decision_for_route, plan_chat_decision


def pending_weather(day="heute"):
    return [
        {"role": "user", "content": f"Wie wird das Wetter {day}?"},
        {"role": "assistant", "content": (
            "Für welchen Ort möchtest du das Wetter wissen? "
            "Nenne mir bitte eine Stadt oder Postleitzahl."
        )},
    ]


def grounded_weather():
    return [
        {"role": "user", "content": "Wie wird das Wetter heute?"},
        {"role": "assistant", "content": (
            "Für welchen Ort möchtest du das Wetter wissen? "
            "Nenne mir bitte eine Stadt oder Postleitzahl."
        )},
        {"role": "user", "content": "Göppingen"},
        {"role": "assistant", "content": (
            "Wetter für Göppingen, Baden-Württemberg, Deutschland heute "
            "(15.10.2026): neblig."
        ), "weather_location": "Göppingen"},
    ]


def test_missing_location_gives_one_explicit_slot_question():
    decision = plan_chat_decision("Wie wird das Wetter heute?")
    assert decision.kind == "clarify"
    assert decision.missing_slots == ("location",)
    assert decision.intent == "web_search"
    assert decision.query == ""
    assert "Stadt oder Postleitzahl" in decision.clarification


def test_explicit_place_and_unsupported_question():
    assert plan_chat_decision("Wie wird das Wetter heute in Göppingen?").kind == "execute_tool"
    assert plan_chat_decision("Wie funktionieren neuronale Netze?") is None
    assert plan_chat_decision("Wie war das Wetter vor zehn Jahren in Berlin?") is None


def test_confirmation_reply_preserves_requested_tomorrow():
    d = plan_chat_decision("Göppingen", pending_weather("morgen"))
    assert d.kind == "execute_tool"
    assert d.query == "Wie wird das Wetter morgen in Göppingen?"


def test_verified_location_used_for_next_day_after_slot_reply():
    d = plan_chat_decision("Und morgen?", grounded_weather())
    assert d.kind == "execute_tool"
    assert d.query == "Wie wird das Wetter morgen in Göppingen?"


def test_free_text_after_weather_question_is_not_a_location():
    assert plan_chat_decision("Kannst du mir bitte einen Text schreiben", pending_weather()) is None
    assert plan_chat_decision("News von heute", pending_weather()) is None
    assert plan_chat_decision("ja", pending_weather()) is None


def test_no_leakage_from_old_or_unrelated_messages():
    unrelated = [
        {"role": "user", "content": "Ich wohne in Göppingen."},
        {"role": "assistant", "content": "Okay."},
    ]
    assert plan_chat_decision("Und morgen?", unrelated) is None
    assert plan_chat_decision("Göppingen", unrelated) is None


def test_routing_contract_covers_normal_answer_and_tools():
    assert decision_for_route({"intent": "normal_chat"})["kind"] == "answer"
    assert decision_for_route({"intent": "web_search"})["kind"] == "execute_tool"


def test_preflight_and_execution_share_clarification_contract():
    client = TestClient(app.app, base_url="http://localhost")
    payload = {"prompt": "Wie wird das Wetter heute?", "conversation_context": []}
    route = client.post("/api/chat/actions/route", json=payload)
    action = client.post("/api/chat/actions", json=payload | {"resolved_target": "chat"})
    assert route.status_code == action.status_code == 200
    assert route.json()["intent"] == "web_search"
    assert route.json()["decision"]["kind"] == "clarify"
    result = action.json()
    assert result["tool"] == "web_search"
    assert result["data"]["routing"]["decision"]["kind"] == "clarify"
    assert result["data"]["weather_forecast"]["status"] == "location_required"


def test_preflight_and_execution_share_confirmed_weather_followup():
    client = TestClient(app.app, base_url="http://localhost")
    history = pending_weather("morgen")
    with mock.patch.object(app, "_weather_search_result", return_value={
        "provider": "Open-Meteo",
        "weather_forecast": {"status": "available", "answer": "verified"},
        "count": 0, "results": [],
    }) as provider:
        route = client.post("/api/chat/actions/route", json={
            "prompt": "Göppingen", "conversation_context": history
        })
        result = client.post("/api/chat/actions", json={
            "prompt": "Göppingen", "conversation_context": history,
            "resolved_target": "chat",
        })
    assert route.status_code == result.status_code == 200
    assert route.json()["decision"]["kind"] == "execute_tool"
    assert result.json()["tool"] == "web_search"
    assert result.json()["data"]["context_resolution"] == "explicit_weather_followup"
    assert result.json()["data"]["routing"]["decision"]["kind"] == "execute_tool"
    provider.assert_called_once_with("Wie wird das Wetter morgen in Göppingen?")


def test_explicit_media_action_not_hijacked_by_weather():
    req = app.ChatActionRequest(prompt="Wie wird das Wetter?", action="image_generate")
    assert app._chat_decision_for_request(req, None) is None
    req = app.ChatActionRequest(prompt="Wie wird das Wetter?", file_context={"kind": "image"})
    assert app._chat_decision_for_request(req, req.file_context) is None


def test_news_stays_with_existing_semantic_router():
    assert plan_chat_decision("Zeige mir die wichtigsten News von heute") is None



def test_next_day_api_uses_verified_city_without_running_semantic_model():
    client = TestClient(app.app, base_url="http://localhost")
    history = grounded_weather()
    with mock.patch.object(app, "_weather_search_result", return_value={
        "provider": "Open-Meteo",
        "weather_forecast": {"status": "available", "answer": "Tomorrow"},
        "count": 0, "results": [],
    }) as weather:
        response = client.post("/api/chat/actions", json={
            "prompt": "Und morgen?", "conversation_context": history,
            "resolved_target": "chat",
        })
    assert response.status_code == 200
    assert response.json()["tool"] == "web_search"
    assert response.json()["data"]["context_resolution"] == "explicit_weather_followup"
    weather.assert_called_once_with("Wie wird das Wetter morgen in Göppingen?")
