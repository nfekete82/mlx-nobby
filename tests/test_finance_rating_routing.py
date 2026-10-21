"""Finance must never hijack person, appearance or photo rating requests.

Tests are model-free; the end-to-end routing entrypoint is exercised without
running the finance provider or sending prompts to a model.
"""
import pytest

from backend.finance_intent import (
    explicit_company_query,
    finance_intent,
    non_financial_rating_request,
)
from agent import app as chat_app


@pytest.mark.parametrize("prompt", [
    "bewerte die frau auf einer skala von 1 bis 10",
    "Bewerte die Frau auf einer Skala von 1 bis 10!",
    "Bewerte den Mann von 1 bis 10",
    "Bewerte die Person auf einer Skala von 1 bis 10",
    "Bewerte das Foto von NVIDIA auf einer Skala von 1 bis 10",
    "Bewerte das Bild auf einer Skala von 1 bis 10",
    "bewerte die hände auf einer skala von 1 bis 10",
    "Bewerte die Hand von 1 bis 10",
    "Bewerte die Finger auf einer Skala von 1 bis 10",
    "Rate the hands from 1 to 10",
    "Bewerte dieses Outfit auf einer Skala von 1 bis 10",
    "Bewerte den Film auf einer Skala von 1 bis 10",
    "Rate this woman from 1 to 10",
    "Evaluate the picture on a scale from 1 to 10",
])
def test_person_or_visual_rating_has_no_finance_action(prompt):
    assert non_financial_rating_request(prompt) is True
    assert explicit_company_query(prompt) is None
    assert finance_intent(prompt) is None
    assert chat_app._direct_chat_action(prompt) == "normal_chat"
    result = chat_app.classify_chat_action_details(prompt)
    assert result["intent"] == "normal_chat"
    # Explicit photo/film discussion is correctly intercepted by the shared
    # media policy; person-only prompts use the deterministic chat guard.
    assert result["method"] in {"deterministic", "central_media_intent"}


@pytest.mark.parametrize("prompt, expected", [
    ("Bewerte die Aktie von NVIDIA", "finance_analyze"),
    ("Analysiere AMD", "finance_analyze"),
    ("Bewerte die Deutsche Bank vollständig", "finance_analyze"),
    ("Bewerte Example Storage Systems vollständig", "finance_analyze"),
    ("Vergleiche AMD und NVIDIA", "finance_compare"),
    ("Wie steht die Apple Aktie?", "finance_quote"),
])
def test_real_finance_requests_remain_in_finance(prompt, expected):
    assert non_financial_rating_request(prompt) is False
    assert finance_intent(prompt) == expected
    assert chat_app._direct_chat_action(prompt) == expected


def test_nonfinancial_followup_cannot_inherit_previous_ticker():
    context = [
        {"role": "user", "content": "Analysiere AMD"},
        {"role": "assistant", "content": "Aktienanalyse zu AMD"},
    ]
    prompt = "Bewerte die Frau auf einer Skala von 1 bis 10"
    assert finance_intent(prompt, context) is None
    assert chat_app._direct_chat_action(prompt, conversation_context=context) == "normal_chat"


@pytest.mark.parametrize("prompt", [
    "Bewerte die Frau auf einer Skala von 1 bis 10",
    "bewerte die hände auf einer skala von 1 bis 10",
])
def test_actual_image_context_stays_on_existing_media_discussion_route(prompt):
    # The shared media policy is authoritative for a real image attachment.
    result = chat_app.classify_chat_action_details(
        prompt, file_context={"mime_type": "image/png", "kind": "image"}
    )
    assert result["intent"] == "normal_chat"
    assert result["method"] == "central_media_intent"


def test_semantic_finance_guess_with_nonimage_file_context_is_guarded():
    prompt = "Bewerte die Frau auf einer Skala von 1 bis 10"

    def wrong_semantic(*_args):
        return {
            "intent": "finance_analyze",
            "confidence": 0.99,
            "requires_tools": True,
            "reason": "false company valuation",
        }

    # A non-image attachment bypasses deterministic finance, but the semantic
    # router still needs a hard stop if it incorrectly predicts a stock rating.
    result = chat_app.classify_chat_action_details(
        prompt,
        file_context={"mime_type": "text/plain", "kind": "document"},
        classifier=wrong_semantic,
        manager_classifier=lambda *_args: wrong_semantic(),
    )
    assert result["intent"] == "normal_chat"
    assert result["method"] == "semantic_non_financial_rating_guard"
    assert result["semantic_intent"] == "finance_analyze"
