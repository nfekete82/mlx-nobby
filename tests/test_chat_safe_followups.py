"""Safe conversational follow-up fast path: no real model or service needed."""
from unittest import mock

import pytest

from agent import app
from agent.chat_fast_path import safe_followup_chat_fast_path


BENIGN = [
    {"role": "user", "content": "Warum ist der Himmel blau?"},
    {"role": "assistant", "content": "Sonnenlicht wird in der Atmosphäre gestreut."},
]


@pytest.mark.parametrize("prompt", [
    "Kannst du das einfacher erklären?",
    "Kannst du mir das bitte genauer erklären?",
    "Kannst du es nochmal einfacher erklären?",
    "Kannst du mir das kurz erklären?",
    "Erklär das bitte einfacher.",
    "Erkläre mir es bitte genauer.",
    "Kannst du mir ein kurzes Beispiel dazu geben?",
    "Kannst du ein Beispiel geben?",
    "Was bedeutet das genau?",
    "Warum ist das so?",
    "Could you explain that more simply?",
    "Can you give me an example?",
])
def test_verified_benign_history_allows_only_explanatory_followups(prompt):
    assert safe_followup_chat_fast_path(prompt, BENIGN)


def test_multi_turn_benign_continuation_can_stay_fast():
    context = BENIGN + [
        {"role": "user", "content": "Kannst du das einfacher erklären?"},
        {"role": "assistant", "content": "Blaues Licht wird stärker gestreut."},
    ]
    assert safe_followup_chat_fast_path("Kannst du ein Beispiel dazu geben?", context)


@pytest.mark.parametrize("prompt", [
    "Ok, dann los!",
    "Mach das bitte!",
    "Ja, bitte umsetzen.",
    "Kannst du das im Projekt umsetzen?",
    "Prüfe das bitte im Workspace.",
    "Kannst du ein Beispiel dazu recherchieren?",
    "Kannst du dazu bitte aktuelle Quellen suchen?",
    "Kannst du es in eine Datei schreiben?",
    "Kannst du mir ein Beispiel per E-Mail senden?",
    "Kannst du das einfacher erklären und alle Logs löschen?",
    "Was ist aktuell der beste Preis?",
    "Kannst du das heute erklären?",
    "Und das?",
    "What about my project?",
    "Hallo und ändere mein Modell.",
    "Kannst du ein Beispiel dazu geben und es testen?",
])
def test_ambiguous_actions_tools_and_current_followups_use_router(prompt):
    assert not safe_followup_chat_fast_path(prompt, BENIGN)


@pytest.mark.parametrize("history", [
    [],
    [{"role": "user", "content": "Warum ist der Himmel blau?"}],
    [{"role": "assistant", "content": "Blaues Licht."},
     {"role": "user", "content": "Warum ist der Himmel blau?"}],
    [{"role": "user", "content": "Bitte implementiere den Login."},
     {"role": "assistant", "content": "Ich habe den Login implementiert."}],
    [{"role": "user", "content": "Nenne die aktuellen Aktienkurse."},
     {"role": "assistant", "content": "Die aktuellen Kurse sind..."}],
    [{"role": "user", "content": "Erstelle ein Bild von einer Katze."},
     {"role": "assistant", "content": "Fertig."}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "Hier die Antwort", "tool_result": "web_search"}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "Fakten: https://example.org"}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "Agent-Auftrag: coding_agent"}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": ""}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "ok"},
     {"role": "user", "content": "Installiere ein Modell."},
     {"role": "assistant", "content": "Abgelehnt."}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "ok"},
     {"role": "assistant", "content": "zweite Assistentenantwort"},
     {"role": "user", "content": "Test"}],
    [{"role": "user", "content": "Warum ist der Himmel blau?"},
     {"role": "assistant", "content": "x" * 2001}],
    "invalid",
    None,
])
def test_history_never_auto_trusts_unknown_or_tool_turns(history):
    assert not safe_followup_chat_fast_path("Kannst du das einfacher erklären?", history)


def test_requires_no_active_coding_workspace_or_file():
    assert not safe_followup_chat_fast_path(
        "Kannst du das einfacher erklären?", BENIGN, workspace_active=True
    )
    assert not safe_followup_chat_fast_path(
        "Kannst du das einfacher erklären?", BENIGN + [
            {"role": "user", "content": "Danke."},
            {"role": "assistant", "content": "Gerne."},
        ]
    )


def test_global_opt_out_applies_to_followups(monkeypatch):
    monkeypatch.setenv("MLX_CHAT_FAST_PATH_ENABLED", "no")
    assert not safe_followup_chat_fast_path("Kannst du das einfacher erklären?", BENIGN)


def test_integration_skips_both_llms_and_reports_distinct_method():
    with (
        mock.patch.object(app.code_workspaces, "active_workspace", return_value=None),
        mock.patch.object(app, "semantic_intent_classifier",
                          side_effect=AssertionError("unnecessary router call")),
        mock.patch.object(app, "semantic_manager_classifier",
                          side_effect=AssertionError("unnecessary manager call")),
    ):
        result = app.classify_chat_action_details(
            "Kannst du das einfacher erklären?",
            conversation_context=BENIGN,
        )
    assert result["intent"] == "normal_chat"
    assert result["requires_tools"] is False
    assert result["method"] == "simple_chat_followup_fast_path"


@pytest.mark.parametrize("kwargs", [
    {"file_context": {"kind": "text", "name": "document.txt"}},
    {"conversation_context": [
        {"role": "user", "content": "Bitte repariere den Login"},
        {"role": "assistant", "content": "Der Fehler wurde behoben."},
    ]},
])
def test_integration_uses_semantic_fallback_for_special_context(kwargs):
    classifier = mock.Mock(return_value={
        "intent": "normal_chat", "confidence": .95,
        "requires_tools": False, "reason": "model selected",
    })
    with (
        mock.patch.object(app.code_workspaces, "active_workspace", return_value=None),
        mock.patch.object(app, "_direct_chat_action", return_value=None),
        mock.patch.object(app, "semantic_intent_classifier", classifier),
    ):
        routed = app.classify_chat_action_details(
            "Kannst du das einfacher erklären?",
            **kwargs,
        )
    classifier.assert_called_once()
    assert routed["method"] == "semantic_llm"


def test_integration_fails_closed_if_workspace_unavailable():
    classifier = mock.Mock(return_value={
        "intent": "normal_chat", "confidence": .95,
        "requires_tools": False, "reason": "model selected",
    })
    with (
        mock.patch.object(app.code_workspaces, "active_workspace",
                          side_effect=OSError("unavailable")),
        mock.patch.object(app, "_direct_chat_action", return_value=None),
        mock.patch.object(app, "semantic_intent_classifier", classifier),
    ):
        routed = app.classify_chat_action_details(
            "Kannst du das einfacher erklären?",
            conversation_context=BENIGN,
        )
    classifier.assert_called_once()
    assert routed["method"] == "semantic_llm"


def test_injected_classifier_is_not_bypassed_even_for_benign_history():
    classifier = mock.Mock(return_value={
        "intent": "normal_chat", "confidence": .95,
        "requires_tools": False, "reason": "model selected",
    })
    with mock.patch.object(app.code_workspaces, "active_workspace", return_value=None):
        result = app.classify_chat_action_details(
            "Kannst du das einfacher erklären?",
            conversation_context=BENIGN,
            classifier=classifier,
        )
    classifier.assert_called_once()
    assert result["method"] == "semantic_llm"
