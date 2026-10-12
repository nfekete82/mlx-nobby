"""Regression coverage for useful fail-closed research responses.

These tests do not substitute for a native quality benchmark.
"""
from agent.semantic_evidence import (
    SemanticClaim, _subjective_preference, verify_candidates, _render,
)
from agent.structured_evidence import EvidenceBundle, EvidenceFact, SourceRecord


def _claim(index, statement, passage_ids=()):
    return SemanticClaim(
        "c-" + str(index), "Apple", "assertion", statement, (),
        statement, tuple(passage_ids),
    )


def _bundle():
    excerpt = "PostgreSQL 17 Released! Posted on 2024-09-26 by PostgreSQL Global Development Group."
    url = "https://www.postgresql.org/about/news/postgresql-17-released-2936/"
    source = SourceRecord("s1", url, url, "www.postgresql.org", "www.postgresql.org",
        "PostgreSQL 17 Released", "2024-09-26", "2026-10-11T08:00:00+00:00",
        excerpt, "loaded", None, "article", "unassessed", 0)
    fact = EvidenceFact("p1", "s1", "source_statement", excerpt, (),
        "s1", excerpt, (0, len(excerpt)), "2024-09-26",
        "2026-10-11T08:00:00+00:00")
    return EvidenceBundle((source,), (fact,))


def test_personal_preference_with_no_sources_is_not_a_fact_check():
    claim = _claim(1, "I prefer blue devices.")
    assert _subjective_preference(claim)
    result = verify_candidates("Preferences", EvidenceBundle((), ()), [claim],
        lambda *_args: (_ for _ in ()).throw(AssertionError("Should not invoke LLM")))
    assert result[0]["status"] == "not_checked"
    assert result[0]["decision_origin"] == "nonfactual_preference"


def test_german_personal_preference_and_factual_statement_distinguished():
    assert _subjective_preference(_claim(1, "Ich bevorzuge blaue Geräte."))
    assert not _subjective_preference(_claim(2, "PostgreSQL 18 wurde 2024 veröffentlicht."))
    assert not _subjective_preference(_claim(3, "I prefer blue because it is cheaper than red."))


def test_unanchored_factual_statement_remains_insufficient():
    result = verify_candidates("Release?", EvidenceBundle((), ()),
        [_claim(1, "PostgreSQL 18 was released in 2024.")], lambda *_: "")
    assert result[0]["status"] == "insufficient_evidence"


def test_model_prompt_requires_direct_same_entity_refutation_not_merely_absence():
    from json import dumps
    messages = []
    def llm(purpose, prompt, max_tokens):
        messages.append(prompt)
        return dumps({"claims": [{"id": "c-1", "status": "insufficient_evidence",
                                  "reason": "Different version.", "passage_ids": []}]})
    result = verify_candidates("Release date", _bundle(),
        [_claim(1, "PostgreSQL 18 was released in 2024.", ("p1",))], llm)
    assert result[0]["status"] == "insufficient_evidence"
    assert "andere Versionen" in messages[0]
    assert "regionales Verkaufsstartdatum" in messages[0]


def test_eight_unverified_apple_claims_render_as_one_notice_and_preserve_audit():
    claims = [_claim(i, "Apple product claim " + str(i)) for i in range(1, 9)]
    decisions = [{"id": c.id, "status": "insufficient_evidence",
                  "passage_ids": []} for c in claims]
    answer = _render(EvidenceBundle((), ()), claims, decisions,
        {"extraction_ms": 0.0, "verification_ms": 0.0})
    assert answer.count("nicht ausreichend") == 1
    assert "Apple product claim" not in answer
    assert len(answer.audit["claims"]) == 8
    assert answer.audit["verified_supported_count"] == 0


def test_confirmed_claim_kept_and_cited_when_another_is_unverified():
    bundle = _bundle()
    claims = [_claim(1, "PostgreSQL 17 Released!", ("p1",)),
              _claim(2, "PostgreSQL 18 Released!", ("p1",))]
    decisions = [{"id": "c-1", "status": "supported", "passage_ids": ["p1"]},
                 {"id": "c-2", "status": "insufficient_evidence", "passage_ids": []}]
    answer = _render(bundle, claims, decisions, {"extraction_ms": 0.0, "verification_ms": 0.0})
    assert "PostgreSQL 17" in answer
    assert "www.postgresql.org" in answer
    assert answer.audit["verified_supported_count"] == 1
