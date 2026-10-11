"""Dated regional sales are checked against the exact claim, region and source.

The scenarios are generic, not hardcoded to the frozen quality corpus.
"""
import json

from agent.regional_sale_start import future_regional_sale_start_conflicts as conflict
from agent.semantic_evidence import SemanticClaim, verify_candidates
from agent.structured_evidence import build_evidence


def check(statement, *texts, as_of="2026-10-11"):
    return conflict(statement, [(str(i), text) for i, text in enumerate(texts)], as_of=as_of)


def test_regional_future_start_conflicts_with_already_started():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Germany on 2026-09-01. In Japan sales begin on 2026-11-01.") == ["0"]


def test_does_not_borrow_another_region_date():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Germany on 2026-11-01.") == []


def test_does_not_borrow_other_product_date():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Other Tablet sales begin in Japan on 2026-11-01.") == []


def test_elapsed_date_is_not_future():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Japan on 2026-09-01.") == []


def test_same_day_not_future():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Japan on 2026-10-11.") == []


def test_conflicting_date_sources_abstain():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Japan on 2026-11-01.",
        "Atlas Tablet sales begin in Japan on 2026-09-01.") == []


def test_unrelated_claim_not_turned_into_sale_start():
    assert check("Atlas Tablet is available in Japan.",
        "Atlas Tablet sales begin in Japan on 2026-11-01.") == []


def test_hedged_future_start_abstains():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales might begin in Japan on 2026-11-01.") == []


def test_multitoken_region_with_variation():
    assert check("Vega Box sales have started in New Zealand.",
        "Vega Box launch. Sales in New Zealand start on 2026-12-20.",
        as_of="2026-11-01") == ["0"]


def test_missing_or_invalid_asof_abstains():
    assert check("Atlas Tablet sales have begun in Japan.",
        "Atlas Tablet sales begin in Japan on 2026-11-01.",
        as_of="invalid") == []


def test_model_insufficient_decision_is_corrected_by_anchor_and_asof():
    text = ("Nova Board sales begin in France on 2026-09-01. "
            "In Belgium sales begin on 2026-12-01. "
            "The release article describes regional sales dates for Nova Board.")
    bundle = build_evidence([{"action": "fetch_url", "status": "completed",
        "result": {"ok": True, "url": "https://example.org/product-release", "text": text}}],
        goal="When are sales starting?")
    assert bundle.facts
    fact = next(f for f in bundle.facts if "Belgium" in f.evidence_excerpt)
    claim = SemanticClaim("c-1", "Nova Board", "sales", "already begun in Belgium",
        (), "Nova Board sales have begun in Belgium.", (fact.id,))
    def llm(purpose, prompt, max_tokens):
        assert purpose == "agent.verify"
        return json.dumps({"claims": [{"id": "c-1", "status": "insufficient_evidence",
            "reason": "Regional sale date is in future", "passage_ids": [fact.id]}]})
    result = verify_candidates("Nova Board Belgium release", bundle, [claim], llm,
        as_of="2026-10-11")
    assert result[0]["status"] == "contradicted"
    assert result[0]["decision_origin"] == "deterministic_temporal"
    assert result[0]["passage_ids"] == [fact.id]


def test_model_insufficient_decision_stays_insufficient_for_other_region():
    text = ("Nova Board sales begin in France on 2026-12-01. "
            "In Belgium sales begin on 2026-09-01. "
            "The release article describes regional sales dates for Nova Board.")
    bundle = build_evidence([{"action": "fetch_url", "status": "completed",
        "result": {"ok": True, "url": "https://example.org/product-release", "text": text}}])
    fact = next(f for f in bundle.facts if "Belgium" in f.evidence_excerpt)
    claim = SemanticClaim("c-1", "Nova Board", "sales", "already begun in Belgium",
        (), "Nova Board sales have begun in Belgium.", (fact.id,))
    llm = lambda purpose, prompt, tokens: json.dumps({
        "claims": [{"id": "c-1", "status": "insufficient_evidence",
                    "reason": "not verified", "passage_ids": [fact.id]}]})
    result = verify_candidates("Nova Board Belgium release", bundle, [claim], llm,
        as_of="2026-10-11")
    assert result[0]["status"] == "insufficient_evidence"
    assert result[0]["decision_origin"] == "model"
