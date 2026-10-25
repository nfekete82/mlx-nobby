"""Regression: web chat sends the current prompt once, not as history."""
from unittest import mock

from fastapi.responses import StreamingResponse

from agent import app as agent_app
from backend import app as web_app
from backend.chat_route_context import route_inputs


def test_first_turn_has_no_history():
    assert route_inputs([
        {"role": "system", "content": "Custom system prompt"},
        {"role": "user", "content": "  Nenne die zwei Farben Rot und Blau in einem Satz.  "},
    ]) == ("Nenne die zwei Farben Rot und Blau in einem Satz.", [])


def test_prior_turns_are_preserved_and_current_turn_excluded_by_position():
    first = "Nenne die zwei Farben Rot und Blau in einem Satz."
    prompt, context = route_inputs([
        {"role": "user", "content": first},
        {"role": "assistant", "content": "Rot und Blau."},
        {"role": "user", "content": first},
    ])
    assert prompt == first
    assert context == [
        {"role": "user", "content": first},
        {"role": "assistant", "content": "Rot und Blau."},
    ]


def test_history_is_bounded_and_ignores_system_and_multimodal_parts():
    entries = [
        {"role": "system", "content": "Never route from system content"},
        *[
            {"role": ("user" if i % 2 == 0 else "assistant"), "content": "x" * 2501}
            for i in range(12)
        ],
        {"role": "assistant", "content": [{"type": "image_url", "image_url": "data:png"}]},
        {"role": "user", "content": "What is a prime number?"},
    ]
    prompt, context = route_inputs(entries)
    assert prompt == "What is a prime number?"
    assert len(context) == 7  # last eight message positions; one is non-text
    assert all(len(item["content"]) == 2000 for item in context)
    assert all(item["role"] in {"assistant", "user"} for item in context)


def test_first_turn_can_use_the_existing_agent_zero_router_fast_path():
    prompt, context = route_inputs([
        {"role": "user", "content": "Nenne die zwei Farben Rot und Blau in einem Satz."},
    ])
    with (
        mock.patch.object(agent_app.code_workspaces, "active_workspace", return_value=None),
        mock.patch.object(agent_app, "semantic_intent_classifier",
                          side_effect=AssertionError("router LLM must not run")),
        mock.patch.object(agent_app, "semantic_manager_classifier",
                          side_effect=AssertionError("manager LLM must not run")),
    ):
        result = agent_app.classify_chat_action_details(prompt, conversation_context=context)

    assert result["intent"] == "normal_chat"
    assert result["method"] == "simple_chat_fast_path"


def test_multiturn_routing_still_preserves_history():
    prompt, context = route_inputs([
        {"role": "user", "content": "Nenne die zwei Farben Rot und Blau in einem Satz."},
        {"role": "assistant", "content": "Rot und Blau."},
        {"role": "user", "content": "Kannst du mir das einfacher erklären?"},
    ])
    assert len(context) == 2
    assert context[-1]["role"] == "assistant"
    with mock.patch.object(agent_app.code_workspaces, "active_workspace", return_value=None):
        result = agent_app.classify_chat_action_details(prompt, conversation_context=context)
    assert result["intent"] == "normal_chat"
    assert result["method"] == "simple_chat_followup_fast_path"


def test_web_stream_routes_without_echoing_current_prompt():
    calls = []

    def fake_agent_json_request(method, path, payload=None, timeout=10):
        calls.append((method, path, payload))
        if path.startswith("/api/profile/context"):
            return {"context": "Nonempty profile context"}
        if path == "/api/chat/route":
            return {"intent": "normal_chat"}
        raise AssertionError(f"Unexpected call: {path}")

    with (
        mock.patch.object(web_app, "agent_json_request",
                          side_effect=fake_agent_json_request),
        mock.patch("backend.weather_forecast.forecast_for_question",
                   return_value=None),
        mock.patch("backend.web_research.needs_web_research",
                   return_value=False),
        mock.patch("backend.live_intelligence.needs_inflation_lookup",
                   return_value=False),
    ):
        result = web_app.mlx_chat_stream(web_app.ChatRequest(
            messages=[{"role": "user", "content": "Nenne die zwei Farben Rot und Blau in einem Satz."}],
            system_prompt="Custom persona",
        ))

    assert isinstance(result, StreamingResponse)
    routes = [payload for _, path, payload in calls if path == "/api/chat/route"]
    assert len(routes) == 1
    assert routes[0]["prompt"] == "Nenne die zwei Farben Rot und Blau in einem Satz."
    assert routes[0]["conversation_context"] == []
