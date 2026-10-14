"""Fast-chat router regressions: no runtime/model/network calls."""
from unittest import mock

import pytest

from agent import app
from agent.chat_fast_path import simple_chat_fast_path


@pytest.mark.parametrize("prompt", [
    "Hallo!",
    "Guten Abend.",
    "Vielen Dank!",
    "Warum ist der Himmel blau?",
    "Was sind Primärfarben?",
    "Wie viele Kontinente hat die Erde?",
    "Nenne die zwei Farben Rot und Blau in einem Satz.",
    "Schreibe ein kurzes Gedicht über Sterne.",
    "Write a short story about a friendly robot.",
    "Explain photosynthesis in simple words.",
])
def test_safe_standalone_chat_prompts_are_eligible(prompt):
    assert simple_chat_fast_path(prompt)


@pytest.mark.parametrize("prompt", [
    "Was sind die aktuell besten Spiele?",
    "Was sind die neuesten MLX-Pipelines?",
    "Wie viele Aktien sind heute gefallen?",
    "Nenne die aktuellen Aktienkurse.",
    "Nenne mir den Preis 2026.",
    "Nenne die Restaurants in Göppingen.",
    "Warum ist mein Mac langsam?",
    "Nenne mir meine Dateien im Workspace.",
    "Nenne den Port meines Servers.",
    "Erkläre mir das nochmal.",
    "Nenne mir die Bilder aus meinem Projekt.",
    "Hallo, lösche meine Daten.",
    "Schreibe ein Gedicht und speichere es in einer Datei.",
    "Nenne mir die Informationen von https://example.org",
    "Nenne die neuesten Nachrichten.",
    "Erkläre mir diesen Code.",
    "Bitte erkläre mir die aktuelle Uhrzeit.",
    "Erkläre bitte den aktuellen Zustand unseres Modells.",
    "Erstelle ein Bild von einem Hund.",
    "Installiere ein neues MLX-Modell.",
    "Führe die Tests aus.",
    "Nenne mir die neuesten Entwicklungen von heute.",
])
def test_nontrivial_current_and_tool_prompts_are_not_fast_pathed(prompt):
    assert not simple_chat_fast_path(prompt)


@pytest.mark.parametrize("context", [
    {"has_file": True},
    {"has_history": True},
    {"workspace_active": True},
])
def test_fast_path_requires_no_implicit_context(context):
    assert not simple_chat_fast_path("Hallo!", **context)
    assert not simple_chat_fast_path("Warum ist der Himmel blau?", **context)


def test_short_safe_chat_bypasses_both_model_classifiers():
    with (
        mock.patch.object(app.code_workspaces, "active_workspace", return_value=None),
        mock.patch.object(app, "semantic_intent_classifier",
                          side_effect=AssertionError("must not call router")),
        mock.patch.object(app, "semantic_manager_classifier",
                          side_effect=AssertionError("must not call manager")),
    ):
        result = app.classify_chat_action_details(
            "Nenne die zwei Farben Rot und Blau in einem Satz.",
        )
    assert result["intent"] == "normal_chat"
    assert result["method"] == "simple_chat_fast_path"
    assert result["requires_tools"] is False
    assert result["confidence"] == 1.0


def test_injected_classifier_is_never_bypassed():
    classifier = mock.Mock(return_value={
        "intent": "normal_chat", "confidence": 0.95, "requires_tools": False,
        "reason": "injected",
    })
    with mock.patch.object(app.code_workspaces, "active_workspace", return_value=None):
        result = app.classify_chat_action_details(
            "Nenne die zwei Farben Rot und Blau in einem Satz.",
            classifier=classifier,
        )
    classifier.assert_called_once()
    assert result["method"] == "semantic_llm"


def test_active_workspace_falls_back_to_semantic_classifier():
    classifier = mock.Mock(return_value={
        "intent": "normal_chat", "confidence": 0.95, "requires_tools": False,
        "reason": "routed",
    })
    with (
        mock.patch.object(app.code_workspaces, "active_workspace", return_value={"path": "/mock"}),
        mock.patch.object(app, "semantic_intent_classifier", classifier),
    ):
        result = app.classify_chat_action_details("Nenne die zwei Farben Rot und Blau.")
    classifier.assert_called_once()
    assert result["method"] != "simple_chat_fast_path"


def test_attached_file_and_history_never_fast_path():
    for options in (
        {"file_context": {"kind": "text", "name": "example.txt"}},
        {"conversation_context": [{"role": "user", "content": "coding_agent workspace"}]},
    ):
        classifier = mock.Mock(return_value={
            "intent": "normal_chat", "confidence": 0.95, "requires_tools": False,
            "reason": "routed",
        })
        with (
            mock.patch.object(app.code_workspaces, "active_workspace", return_value=None),
            mock.patch.object(app, "_direct_chat_action", return_value=None),
            mock.patch.object(app, "semantic_intent_classifier", classifier),
        ):
            result = app.classify_chat_action_details("Warum ist der Himmel blau?", **options)
        classifier.assert_called_once()
        assert result["method"] != "simple_chat_fast_path"


def test_missing_workspace_state_must_fail_closed():
    with (
        mock.patch.object(app.code_workspaces, "active_workspace",
                          side_effect=ValueError("workspace unreadable")),
        mock.patch.object(app, "_direct_chat_action", return_value=None),
        mock.patch.object(app, "semantic_intent_classifier", return_value={
            "intent": "normal_chat", "confidence": 0.95,
            "requires_tools": False, "reason": "routed",
        }) as classifier,
    ):
        result = app.classify_chat_action_details("Warum ist der Himmel blau?")
    classifier.assert_called_once()
    assert result["method"] != "simple_chat_fast_path"
