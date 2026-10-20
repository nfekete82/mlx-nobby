"""Regression: personal coaching text with commercial facts is not web search."""
from unittest import mock
from agent import app as agent_app

EXAMPLE = (
    "mein chef ist so ein riesen vollidiot wir haben o2 angebote auf unserer "
    "webseite, lt. statistiken gehen die besucher drauf aber gehen relativ schnell "
    "wieder und die meisten geben feedback dass es einfach zu teuer ist. "
    "jetzt sagt mein chef aber es liegt daran dass wir es nicht in jedem "
    "newsletter bewerben und er scheißt auf statistiken"
)


def test_workplace_vent_routes_to_normal_chat_without_search():
    with mock.patch.object(agent_app, "semantic_intent_classifier",
                           side_effect=AssertionError("should not need model router")):
        result = agent_app.classify_chat_action_details(EXAMPLE)
    assert result["intent"] == "normal_chat"
    assert result["method"] == "deterministic"


def test_relationship_reflection_does_not_require_web():
    assert agent_app._personal_reflection_chat(
        "Meine Mutter sagt immer ich soll ihr helfen und das ärgert mich")
    assert agent_app._personal_reflection_chat(
        "Mein Chef meint die Website ist das Problem, was hältst du davon?")


def test_explicit_external_search_and_current_facts_still_use_tools():
    for prompt in (
        "Mein Chef sagt, suche im Internet die aktuellen O2 Angebote",
        "Meine Mutter meint, recherchiere aktuelle Nachrichten",
        "Mein Chef behauptet etwas, finde mir Quellen dafür",
    ):
        assert not agent_app._personal_reflection_chat(prompt)
    assert not agent_app._personal_reflection_chat("Was kostet O2 heute?")
