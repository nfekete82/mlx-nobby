"""Production evidence hook integration, including paths without web evidence."""
from dataclasses import replace
import json

from agent.model_provider import ModelRequest
from agent.runtime import current_runtime
from agent.structured_evidence import build_evidence
from agent.semantic_evidence import synthesize_verified_evidence
from backend.observability import model_call_context


ARTICLE = {"action": "fetch_url", "status": "completed", "query": "https://example.org/news",
           "result": {"ok": True, "url": "https://example.org/news", "text":
                      "Aurora Phone is announced for Germany. Its sales start on October 23, 2099. "
                      "No current sale or current price is confirmed by this announcement."}}


def make_runtime(replies, **kwargs):
    # Reuse the existing real permission-registry harness, avoiding a second
    # subtly different runtime fixture contract.
    from test_agent_runtime import AgentRuntimeTests
    harness = AgentRuntimeTests()
    harness.setUp()

    def evidence_answer(goal, observations):
        def llm(purpose, prompt, max_tokens):
            with model_call_context(purpose):
                return current_runtime().complete_model(ModelRequest(
                    [{"role": "user", "content": prompt}], max_tokens=max_tokens,
                )).text
        return synthesize_verified_evidence(goal, observations, llm)
    harness.hooks = replace(harness.hooks, agent_evidence_answer=evidence_answer)
    return harness, harness.runtime(replies, **kwargs)


def replies_for_article():
    pid = build_evidence([ARTICLE]).facts[0].id
    return [
        {"claims": [{"subject": "Aurora Phone", "predicate": "announced", "value": "Germany",
                     "qualifiers": {}, "statement": "Aurora Phone ist für Deutschland angekündigt.",
                     "passage_ids": [pid]}]},
        {"claims": [{"id": "c-1", "status": "supported", "reason": "Die Passage nennt die Ankündigung.",
                     "passage_ids": [pid]}]},
    ]


def test_loaded_source_extracts_and_verifies_without_another_planner_or_free_summary():
    harness, runtime = make_runtime(replies_for_article())
    result = runtime.run("Recherchiere Aurora Phone", observations=[ARTICLE])
    assert result["status"] == "completed"
    assert len(harness.provider.calls) == 2
    assert not harness.planner_limits
    assert "angekündigt" in result["answer"]
    assert "bereits erhältlich" not in result["answer"]
    assert result["evidence"]["independent_truth_verification"] is False
    assert result["evidence"]["claims"][0]["anchors"][0]["source_location"][0] == 0
    purposes = [e["purpose"] for e in result["performance"]["events"] if e.get("action") == "provider.complete"]
    assert purposes == ["agent.extract", "agent.verify"]


def test_direct_planner_answer_cannot_skip_research_evidence():
    harness, runtime = make_runtime([{"action": "final", "answer": "Aurora Phone ist bereits erhältlich."}])
    result = runtime.run("Recherchiere die aktuelle Verfügbarkeit von Aurora Phone.")
    assert "bereits erhältlich" not in result["answer"]
    assert result["evidence"]["selected_count"] == 0
    assert len(harness.provider.calls) == 1


def test_ordinary_nonresearch_chat_preserves_direct_answer():
    harness, runtime = make_runtime([{"action": "final", "answer": "Hallo!"}])
    result = runtime.run("Sag Hallo")
    assert result["answer"] == "Hallo!"
    assert "evidence" not in result


def test_current_local_diagnostics_are_not_mistaken_for_web_research():
    harness, runtime = make_runtime([{"action": "inspect"}, {"action": "final", "answer": "Video nutzt CPU."}])
    result = runtime.run("Welche App hat aktuell den höchsten Systemverbrauch?")
    assert result["answer"] == "Video nutzt CPU."
    assert "evidence" not in result


def test_cancellation_between_extraction_and_verification_keeps_no_supported_answer():
    from agent.model_provider import ProviderError
    harness, runtime = make_runtime([replies_for_article()[0], ProviderError("cancelled", "cancelled")])
    result = runtime.run("Recherchiere Aurora Phone", observations=[ARTICLE])
    assert result["status"] == "cancelled"
    assert result["answer"] == ""
    assert len(harness.provider.calls) == 2



def test_decision_date_and_effective_date_are_separate_in_evidence_prompts():
    """Prevent a decision announcement date from silently becoming 'valid since'."""
    statement = (
        "At its 10 September 2026 meeting, the council decided to raise the "
        "deposit facility rate to 2.50%. The new rate takes effect from "
        "16 September 2026. The announcement was published on 10 September 2026."
    )
    source = {
        "action": "fetch_url", "status": "completed",
        "query": "https://example.org/official/rates",
        "result": {"ok": True, "url": "https://example.org/official/rates",
                   "text": statement},
    }
    goal = "What is the current deposit rate and when did it take effect?"
    passages = build_evidence([source], goal=goal).facts
    assert passages
    pid = next(p.id for p in passages if "takes effect" in p.evidence_excerpt)
    prompts = {}

    def llm(purpose, prompt, max_tokens):
        prompts[purpose] = prompt
        if purpose == "agent.extract":
            return json.dumps({"claims": [{
                "subject": "Deposit facility rate",
                "predicate": "effective_since",
                "value": "16 September 2026",
                "qualifiers": {},
                "statement": "The new deposit facility rate applies from 16 September 2026.",
                "passage_ids": [pid],
            }]})
        return json.dumps({"claims": [{
            "id": "c-1", "status": "supported",
            "reason": "Source explicitly supplies the effective date",
            "passage_ids": [pid],
        }]})

    synthesize_verified_evidence(goal, [source], llm)
    assert "agent.extract" in prompts
    assert "agent.verify" in prompts
    assert "Beschlussdatum" in prompts["agent.extract"]
    assert "Wirksamkeitsdatum" in prompts["agent.verify"]
    assert "seit-X-Behauptung" in prompts["agent.verify"]



def test_institution_attribution_requires_primary_anchor():
    """A secondary article cannot independently certify its subject's policy."""
    goal = "Wie erläutert die Europäische Zentralbank (EZB) ihre aktuelle Geldpolitik?"
    text = (
        "Die Europäische Zentralbank beschreibt ihre Geldpolitik als "
        "wichtigen Bestandteil ihrer Arbeit. Für die weitere Planung "
        "gelten die veröffentlichten Berichte und Mitteilungen."
    )

    def run_with(url):
        source = {
            "action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "text": text},
        }
        bundle = build_evidence([source], goal=goal)
        pid = bundle.facts[0].id

        def llm(purpose, prompt, limit):
            if purpose == "agent.extract":
                return json.dumps({"claims": [{
                    "subject": "Europäische Zentralbank",
                    "predicate": "describes_policy",
                    "value": "Geldpolitik",
                    "qualifiers": {},
                    "statement": "Die Europäische Zentralbank beschreibt ihre Geldpolitik.",
                    "passage_ids": [pid],
                }]})
            return json.dumps({"claims": [{
                "id": "c-1", "status": "supported",
                "reason": "Die Passage nennt die Geldpolitik",
                "passage_ids": [pid],
            }]})

        return synthesize_verified_evidence(goal, [source], llm)

    secondary = run_with("https://www.lbbw.de/artikel/geldpolitik")
    assert secondary.audit["verified_supported_count"] == 0
    assert secondary.audit["claims"][0]["status"] == "insufficient_evidence"
    assert secondary.audit["claims"][0]["decision_origin"] == "primary_source_validation"

    primary = run_with("https://www.ecb.europa.eu/press/official.html")
    assert primary.audit["verified_supported_count"] == 1
    assert primary.audit["claims"][0]["status"] == "supported"



def test_general_research_extraction_excludes_product_lineup_constraints():
    """Influenza and standards extraction should use one short generic contract."""
    from agent.semantic_evidence import _extract_candidates
    goal = "Welche Symptome sind bei Influenza typisch?"
    source = {
        "action": "fetch_url", "status": "completed",
        "query": "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html",
        "result": {
            "ok": True,
            "url": "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html",
            "text": (
                "Die Influenza beginnt oft plötzlich mit Fieber und "
                "Muskel- oder Kopfschmerzen. Ein trockener Reizhusten "
                "kann später hinzukommen. "
            ) * 3,
        },
    }
    bundle = build_evidence([source], goal=goal)
    pid = bundle.facts[0].id
    prompts = []

    def llm(purpose, prompt, max_tokens):
        assert purpose == "agent.extract"
        prompts.append(prompt)
        return json.dumps({"claims": [{
            "subject": "Influenza",
            "predicate": "symptom",
            "value": "Fieber",
            "qualifiers": {},
            "statement": "Typische Influenza kann mit Fieber beginnen.",
            "passage_ids": [pid],
        }]})

    claims, error = _extract_candidates(goal, bundle, llm)
    assert error is None
    assert len(claims) == 1
    assert "Originalpassagen" in prompts[0]
    assert "QUELLEN" not in prompts[0]
    assert "aktuell angebotenen Modellen" not in prompts[0]
    assert "Entdecke alle Modelle" not in prompts[0]
    assert "product" not in prompts[0].lower()
