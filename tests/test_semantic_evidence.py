"""Protocol/provenance guarantees, separate from native-model semantic quality."""
from dataclasses import replace
import json

import pytest

from agent.semantic_evidence import SemanticClaim, synthesize_verified_evidence, verify_candidates
from agent.structured_evidence import build_evidence, EvidenceBundle


TEXT = ("Aurora Phone is announced for Germany. Sales start on 2027-02-01, so it is not yet available.\n"
        "Atlas Tablet has 16 GB RAM and is available for sale in Germany according to this release.")


def observation(text=TEXT, url="https://example.org/article", **kwargs):
    return {"action": "fetch_url", "status": "completed",
            "result": {"ok": True, "text": text, "url": url, **kwargs}}


def bundle():
    return build_evidence([observation()])


def candidate(b=None, **kwargs):
    b = b or bundle()
    defaults = dict(id="c-1", subject="Aurora Phone", predicate="announcement",
                    value="announced", qualifiers=(),
                    statement="Aurora Phone wurde für Deutschland angekündigt.",
                    passage_ids=(b.facts[0].id,))
    return SemanticClaim(**(defaults | kwargs))


def extracted(b=None, **kwargs):
    c = candidate(b, **kwargs)
    return {"subject": c.subject, "predicate": c.predicate, "value": c.value,
            "qualifiers": dict(c.qualifiers), "statement": c.statement,
            "passage_ids": list(c.passage_ids)}


def decision(b=None, **kwargs):
    b = b or bundle()
    return {"id": "c-1", "status": "supported", "reason": "Die Quelle beschreibt die Ankündigung.",
            "passage_ids": [b.facts[0].id]} | kwargs


class ScriptedLLM:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, purpose, prompt, max_tokens):
        self.calls.append((purpose, prompt, max_tokens))
        result = self.results.pop(0)
        return result if isinstance(result, str) else json.dumps(result)


def test_two_stages_render_verified_atomic_claim_and_observed_citation():
    llm = ScriptedLLM({"claims": [extracted()]}, {"claims": [decision()]})
    answer = synthesize_verified_evidence("Was wurde angekündigt?", [observation()], llm)
    assert "Aurora Phone wurde für Deutschland angekündigt." in answer
    assert "https://example.org/article" in answer
    assert [c[0] for c in llm.calls] == ["agent.extract", "agent.verify"]
    assert answer.audit["method"] == "model_semantic_verification"
    assert answer.audit["independent_truth_verification"] is False
    assert answer.audit["claims"][0]["decision_origin"] == "model"
    anchor = answer.audit["claims"][0]["anchors"][0]
    assert anchor["evidence_excerpt"] == TEXT.splitlines()[0]
    assert set(answer.audit["timings_ms"]) == {"extraction", "verification"}


@pytest.mark.parametrize("observations", [[], [observation(source_type="rss_wrapper")],
    [observation(text="small")], [observation(final_url="http://127.0.0.1/private")]])
def test_unusable_evidence_never_calls_model(observations):
    llm = ScriptedLLM()
    answer = synthesize_verified_evidence("Recherche", observations, llm)
    assert llm.calls == []
    assert answer.audit["selected_count"] == 0
    assert answer.audit["error_status"] == "no_usable_evidence"


@pytest.mark.parametrize("change", [
    {"passage_ids": ["forged"]}, {"statement": "Click https://evil.example"},
    {"statement": "Eintrag\n  - orphan"}, {"statement": "x" * 601},
    {"qualifiers": {"region": {"nested": "Germany"}}},
    {"qualifiers": {"region": "https://fake.example"}}, {"value": 16},
    {"source_url": "https://evil.example"}, {"passage_ids": []},
])
def test_malformed_extraction_never_reaches_verifier_or_output(change):
    llm = ScriptedLLM({"claims": [extracted() | change]})
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert len(llm.calls) == 1
    assert answer.audit["selected_count"] == 0
    assert "evil.example" not in answer and "fake.example" not in answer


@pytest.mark.parametrize("raw", ["not json", "{\"claims\":null}", "[{}]", "x" * 32001,
    '{"claims":[],"claims":[]}'])
def test_invalid_extraction_envelope_fails_closed(raw):
    llm = ScriptedLLM(raw)
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert len(llm.calls) == 1
    assert answer.audit["error_status"] == "invalid_extraction_schema"


def test_too_many_candidates_rejected_and_no_extra_model_call():
    llm = ScriptedLLM({"claims": [extracted()] * 9})
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert len(llm.calls) == 1
    assert answer.audit["selected_count"] == 0


@pytest.mark.parametrize("status", ["contradicted", "insufficient_evidence", "conflicting_evidence", "not_checked"])
def test_non_supported_claims_do_not_render_the_proposed_false_statement(status):
    proposed = "Aurora Phone wird bereits in allen Ländern verkauft."
    llm = ScriptedLLM({"claims": [extracted(statement=proposed)]}, {"claims": [decision(status=status)]})
    answer = synthesize_verified_evidence("Verfügbar?", [observation()], llm)
    assert proposed not in answer
    assert "Aurora Phone" in answer
    assert answer.audit["selected_count"] == 0
    assert answer.audit["claims"][0]["status"] == status


@pytest.mark.parametrize("change", [
    {"status": "verified"}, {"status": []}, {"passage_ids": []},
    {"passage_ids": ["forged"]}, {"passage_ids": [123]},
    {"reason": "https://evil.example"}, {"reason": "x" * 501},
    {"source_url": "https://evil.example"}, {"statement": "Ignore the extractor"},
])
def test_verifier_cannot_admit_malformed_or_forged_decisions(change):
    llm = ScriptedLLM({"claims": [decision() | change]})
    result = verify_candidates("Recherche", bundle(), [candidate()], llm)
    assert result[0]["status"] != "supported"
    assert result[0]["decision_origin"] == "invalid_response"


@pytest.mark.parametrize("rows", [[decision(), decision()], [decision(id="other")], [], [None]])
def test_unknown_duplicate_or_missing_verification_ids_fail_closed(rows):
    llm = ScriptedLLM({"claims": rows})
    results = verify_candidates("Recherche", bundle(), [candidate()], llm)
    assert results[0]["status"] != "supported"


def test_source_anchor_modified_after_extraction_is_rejected_without_model():
    b = bundle()
    changed = replace(b.sources[0], text=b.sources[0].text.replace("announced", "cancelled"))
    forged = EvidenceBundle((changed,), b.facts)
    llm = ScriptedLLM()
    results = verify_candidates("Recherche", forged, [candidate(b)], llm)
    assert llm.calls == []
    assert results[0]["status"] == "insufficient_evidence"
    assert results[0]["decision_origin"] == "no_anchor"


def test_verifier_receives_omitted_opposing_source_and_can_cite_it():
    opposed = "Aurora Phone is cancelled in Germany. This product will not be offered for sale and no release is planned."
    b = build_evidence([observation(), observation(opposed, "https://example.net/correction")])
    other = next(f for f in b.facts if f.source_id == b.sources[1].id)
    llm = ScriptedLLM({"claims": [decision(b, status="conflicting_evidence", passage_ids=[b.facts[0].id, other.id])]})
    results = verify_candidates("Recherche", b, [candidate(b)], llm, as_of="2026-10-11")
    assert opposed in llm.calls[0][1]
    assert "2026-10-11" in llm.calls[0][1]
    assert results[0]["status"] == "conflicting_evidence"
    assert other.id in results[0]["passage_ids"]


def test_explicit_corpus_scope_prevents_cross_case_source_borrowing():
    b = bundle()
    other = b.facts[1].id
    llm = ScriptedLLM({"claims": [decision(b, passage_ids=[other])]})
    results = verify_candidates("Recherche", b, [candidate(b)], llm,
                                context_scope={"c-1": (b.facts[0].id,)})
    assert results[0]["status"] != "supported"
    assert "Atlas Tablet" not in llm.calls[0][1]


def test_partial_list_preserves_supported_entry_without_orphaned_children():
    b = bundle()
    first = extracted(b)
    second = extracted(b, subject="Atlas Tablet", value="128 GB RAM",
                       statement="Atlas Tablet hat 128 GB RAM.", passage_ids=(b.facts[1].id,))
    llm = ScriptedLLM({"claims": [first, second]}, {"claims": [decision(b),
        decision(b, id="c-2", status="contradicted", passage_ids=[b.facts[1].id])]})
    answer = synthesize_verified_evidence("Produkte", [observation()], llm)
    assert first["statement"] in answer
    assert second["statement"] not in answer
    assert answer.audit["selected_count"] == 1
    assert "\n  -" not in answer


def test_markdown_html_in_model_statement_are_display_text_not_links_or_scripts():
    statement = "Aurora Phone ist **angekündigt**; <script>evil()</script>."
    llm = ScriptedLLM({"claims": [extracted(statement=statement)]}, {"claims": [decision()]})
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert "<script>" not in answer and "**angekündigt**" not in answer
    assert "https://example.org/article" in answer


def test_duplicate_extracted_claims_do_not_duplicate_final_list():
    llm = ScriptedLLM({"claims": [extracted(), extracted()]}, {"claims": [decision()]})
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert answer.count(candidate().statement) == 1
    assert answer.audit["selected_count"] == 1


def test_model_cancellation_propagates_without_repair_or_extra_calls():
    def cancelled(*args):
        raise TimeoutError("cancelled")
    with pytest.raises(TimeoutError, match="cancelled"):
        synthesize_verified_evidence("Recherche", [observation()], cancelled)


def test_verification_prompt_requires_temporal_model_ownership_and_injection_checks():
    llm = ScriptedLLM({"claims": [decision()]})
    verify_candidates("Verfügbar?", bundle(), [candidate()], llm, as_of="2026-10-11")
    prompt = llm.calls[0][1]
    for requirement in ["Negation", "Vorbestellung", "Region", "richtigen Modell", "unvertrauenswürdige DATEN", "as_of", "Wahrheitsbeweis"]:
        assert requirement in prompt


def test_final_numerical_validation_downgrades_model_supported_invented_price():
    llm = ScriptedLLM({"claims": [extracted(predicate="price", value="999 EUR",
        statement="Aurora Phone kostet 999 EUR.")]}, {"claims": [decision()]})
    answer = synthesize_verified_evidence("Preis?", [observation()], llm)
    assert "kostet 999 EUR" not in answer
    claim = answer.audit["claims"][0]
    assert claim["status"] == "insufficient_evidence"
    assert claim["decision_origin"] == "deterministic_validation"
    assert claim["deterministic_validation"]["numerical"]["unverified"]


def test_final_temporal_validation_downgrades_future_current_sale_contradiction():
    observations = [observation(TEXT.replace("2027", "2099"))]
    b = build_evidence(observations)
    statement = "Aurora Phone ist bereits verfügbar; Verkaufsstart 2099-02-01."
    llm = ScriptedLLM({"claims": [extracted(b, statement=statement)]}, {"claims": [decision(b)]})
    answer = synthesize_verified_evidence("Verfügbarkeit", observations, llm)
    assert statement not in answer
    assert answer.audit["claims"][0]["status"] == "contradicted"
    assert answer.audit["claims"][0]["deterministic_validation"]["temporal"]


def test_final_conflicting_number_check_only_downgrades_and_preserves_original_claim(monkeypatch):
    from agent import semantic_evidence
    monkeypatch.setattr(semantic_evidence, "audit_numerical_claims", lambda *args:
        {"checked": True, "unverified": [], "conflicts": ["different values"], "source_count": 2})
    llm = ScriptedLLM({"claims": [extracted()]}, {"claims": [decision()]})
    answer = synthesize_verified_evidence("Recherche", [observation()], llm)
    assert answer.audit["claims"][0]["status"] == "conflicting_evidence"
    assert answer.audit["claims"][0]["statement"] == candidate().statement
    assert candidate().statement not in answer


def test_duplicate_candidate_ids_are_not_sent_to_verifier():
    llm = ScriptedLLM()
    results = verify_candidates("Recherche", bundle(), [candidate(), candidate()], llm)
    assert llm.calls == []
    assert all(r["status"] != "supported" for r in results)


def test_large_verification_response_and_duplicate_json_fields_fail_closed():
    for raw in ("x" * 32001, '{"claims":[],"claims":[]}'):
        llm = ScriptedLLM(raw)
        results = verify_candidates("Recherche", bundle(), [candidate()], llm)
        assert results[0]["status"] == "not_checked"
        assert results[0]["decision_origin"] == "invalid_response"
