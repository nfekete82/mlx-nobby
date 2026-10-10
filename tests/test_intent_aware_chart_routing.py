"""Intent-aware chart routing guards real securities without treating figures as stocks."""
from backend.finance_intent import finance_intent, user_supplied_dataset


MONTHLY = (
    "Zeige die Entwicklung dieser sechs Monatsumsätze als interaktives Diagramm: "
    "Januar 12.000 €, Februar 15.000 €, März 13.500 €, "
    "April 19.000 €, Mai 22.000 €, Juni 26.000 €. Erkläre den Trend."
)


def test_user_supplied_figures_have_no_finance_intent():
    assert user_supplied_dataset(MONTHLY)
    assert finance_intent(MONTHLY) is None
    assert user_supplied_dataset("Plot monthly revenue: Jan 12000, Feb 14000, March 16000.")
    assert not user_supplied_dataset("Was ist die Inflation?")
    assert not user_supplied_dataset("Zeige mir ein Diagramm")


def test_explicit_market_securities_still_use_finance():
    assert not user_supplied_dataset("Zeige AMD Aktie 2023 2024 2025 als Chart")
    assert finance_intent("Wie steht AMD gerade?") == "finance_quote"
    assert finance_intent("Vergleiche AMD und NVIDIA") == "finance_compare"


def test_semantic_market_false_positive_is_rejected():
    from agent.app import classify_chat_action_details
    wrong_finance = lambda *args: {
        "intent": "finance_quote", "confidence": 0.98, "requires_tools": True,
        "reason": "mistaken for stock revenue",
    }
    result = classify_chat_action_details(
        MONTHLY, classifier=wrong_finance,
        manager_classifier=lambda *args: wrong_finance(),
    )
    assert result["intent"] == "normal_chat"
    assert result["method"] in {"semantic_data_guard", "deterministic"}
    assert result.get("requires_tools") is False
