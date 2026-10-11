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



def test_morphological_topic_ranking_keeps_relevant_medical_excerpt():
    """A query for Symptome must also surface primary text saying Symptomatik."""
    from agent.structured_evidence import build_evidence
    goal = "Welche typischen Symptome einer Influenza nennt das Robert Koch-Institut?"
    navigation = "\n".join(
        f"Influenza Informationen und allgemeine Dokumentation Abschnitt {i}."
        for i in range(160)
    )
    symptom = (
        "Die Influenza-typische Symptomatik ist oft durch einen plötzlichen "
        "Erkrankungsbeginn mit Fieber, Muskel- und Kopfschmerzen gekennzeichnet."
    )
    body = navigation + "\n" + symptom + "\n"
    url = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    observations = [{
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": True, "url": url, "text": body},
    }]
    bundle = build_evidence(observations, goal=goal)
    assert bundle.facts
    assert symptom in [p.evidence_excerpt for p in bundle.facts]
    # Ranking affects admission, not truth. The quote remains byte exact.
    assert any(
        body[p.source_location[0]:p.source_location[1]] == symptom
        for p in bundle.facts if p.evidence_excerpt == symptom
    )



def test_evidence_budget_keeps_source_exact_passages_from_late_third_document():
    """Long preceding pages cannot consume the entire 100-passage budget."""
    from agent.structured_evidence import build_evidence, evaluate_claim
    from dataclasses import asdict
    sources = []
    for page in range(3):
        url = f"https://www.rfc-editor.org/info/rfc{791 + page}/"
        lines = [
            f"Source document {page} address width measurement context line {i}."
            for i in range(120)
        ]
        sources.append({
            "action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "text": "\n".join(lines)},
        })
    bundle = build_evidence(sources, goal="Welche Adresslängen in Bit werden genannt?")
    assert len(bundle.facts) <= 100
    for source in bundle.sources:
        facts = [f for f in bundle.facts if f.source_id == source.id]
        assert facts, "Even the last loaded article must receive evidence capacity"
        for fact in facts:
            assert evaluate_claim(asdict(fact), [asdict(source)])["status"] == "supported"


def test_single_source_retains_full_evidence_passage_capacity():
    from agent.structured_evidence import build_evidence
    source = {
        "action": "fetch_url", "status": "completed",
        "query": "https://www.rfc-editor.org/info/rfc8200/",
        "result": {
            "ok": True,
            "url": "https://www.rfc-editor.org/info/rfc8200/",
            "text": "\n".join(
                f"Protocol addressing field statement {i} includes source context."
                for i in range(95)
            ),
        },
    }
    bundle = build_evidence([source], goal="Protocol address specifications")
    assert len(bundle.facts) >= 75



def test_short_effective_date_is_anchored_next_to_rate_without_claiming_its_meaning():
    """A 17-char ECB date must reach the verifier, not vanish due to line length."""
    from dataclasses import asdict
    from agent.structured_evidence import (
        _temporal_windows, build_evidence, evaluate_claim,
    )
    url = "https://www.ecb.europa.eu/home/html/index.en.html"
    question = (
        "Wie hoch ist aktuell der Einlagezins der Europäischen Zentralbank, "
        "und seit welchem Datum gilt dieser Zinssatz?"
    )
    text = (
        "Interest rates\n"
        "| Deposit facility | 2.50 %\n"
        "| Main refinancing operations | 2.65 %\n"
        "| Marginal lending facility | 2.90 %\n"
        "16 September 2026\n"
        "Past key ECB interest rates\n"
        "21 September 2026\n"
        "Some unrelated financial press coverage.\n"
    )
    window = _temporal_windows(question, text)
    assert window and any(
        "Deposit facility | 2.50 %" in excerpt
        and "16 September 2026" in excerpt
        for _, _, excerpt in window
    )
    source = {
        "action": "fetch_url", "status": "completed",
        "query": url,
        "result": {"ok": True, "url": url, "text": text, "offset": 35559},
    }
    bundle = build_evidence([source], goal=question)
    dated = [
        fact for fact in bundle.facts if "-date-" in fact.id
        and "16 September 2026" in fact.evidence_excerpt
    ]
    assert dated
    original = asdict(bundle.sources[0])
    for fact in dated:
        assert evaluate_claim(asdict(fact), [original])["status"] == "supported"
        assert fact.source_location[0] >= 35559
    # Extractive evidence alone DOES NOT certify that the date is valid-from.
    assert all(fact.predicate == "source_statement" for fact in dated)


def test_temporal_windows_do_not_borrow_unrelated_press_dates():
    from agent.structured_evidence import _temporal_windows
    question = "Welcher Einlagezins gilt seit welchem Datum?"
    unrelated = (
        "Deposit facility | 2.50 %\n"
        + "An unrelated long introduction " * 35
        + "\n8 October 2026\n"
        + "Press release published today.\n"
    )
    assert _temporal_windows(question, unrelated) == []
    assert _temporal_windows("Was ist die Bank?", unrelated) == []
