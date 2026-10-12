"""A fact can be correctly quoted yet irrelevant to a catalog question."""
import json

from agent.catalog_evidence import catalog_claim_is_lineup, catalog_source_windows
from agent.semantic_evidence import SemanticClaim, synthesize_verified_evidence
from agent.structured_evidence import build_evidence
from agent.semantic_evidence import _anchored_passages

GOAL = "Welche aktuellen iPhone-Modelle bietet Apple offiziell an?"
URL = "https://www.apple.com/de/iphone/"
TEXT = (
    "iPhone. Auf der Apple Website gibt es Produktinformationen.\n"
    "Kameras mit 48 MP und spektakuläre Aufnahmen für die ganze Familie.\n"
    "Entdecke alle Modelle.\n"
    "iPhone Duo Neu. Preise ansehen.\n"
    "iPhone 18 Pro Neu. Jetzt kaufen.\n"
    "iPhone Air. Jetzt kaufen.\n"
    "iPhone 17. Jetzt kaufen.\n"
    "iPhone 17e. Jetzt kaufen.\n"
    "iPhone 16. Jetzt kaufen.\n"
    "Apple Store bietet dir Informationen über alle verfügbaren iPhone Modelle.\n"
    "Außerdem werden Bilder, Datenschutz und zahlreiche weitere Features beschrieben."
)


def observed():
    return [{"action": "fetch_url", "status": "completed",
             "result": {"ok": True, "url": URL, "text": TEXT}}]


def make_claim(statement, subject="iPhone 18 Pro", value="iPhone 18 Pro", passage_ids=()):
    return {"subject": subject, "predicate": "catalog_listing",
            "value": value, "qualifiers": {},
            "statement": statement, "passage_ids": list(passage_ids)}


def scripted(*answers):
    expected = list(answers)
    calls = []

    def llm(purpose, prompt, max_tokens):
        calls.append((purpose, prompt))
        if not expected:
            raise AssertionError("No further model call expected")
        return json.dumps(expected.pop(0), ensure_ascii=False)

    return llm, calls


def test_extract_source_exact_model_block_with_real_offsets():
    windows = catalog_source_windows(GOAL, TEXT)
    assert windows
    assert "iPhone 18 Pro" in windows[0][2]
    for start, end, excerpt in windows:
        assert TEXT[start:end] == excerpt


def test_preserve_short_catalog_cards_that_normal_sentence_split_drops():
    bundle = build_evidence(observed(), goal=GOAL)
    catalog_facts = [f for f in bundle.facts if "-catalog-" in f.id]
    assert catalog_facts
    assert "iPhone 18 Pro" in catalog_facts[0].evidence_excerpt
    anchored = _anchored_passages(bundle)
    assert catalog_facts[0].id in anchored
    assert bundle.sources[0].final_url == URL


def test_catalog_quote_does_not_change_regular_research_mode():
    assert catalog_source_windows("Was ist eine Kamera mit 48 MP?", TEXT) == []
    assert not [f for f in build_evidence(observed(), goal="Welche Kamera?").facts
                if "-catalog-" in f.id]


def test_catalog_relevance_rejects_true_technical_specs():
    features = [
        "Das iPhone 18 Pro hat eine 48 MP Kamera.",
        "Das iPhone Duo unterstützt On-Device KI.",
        "Das iPhone 18 Pro kann Dolby Vision Videos aufnehmen.",
        "Alle iPhone Batterien enthalten recyceltes Kobalt.",
        "Apple Intelligence wird auf dem iPhone verarbeitet.",
        "Das iPhone 18 Pro nutzt Ceramic Shield 2.",
    ]
    for text in features:
        claim = SemanticClaim("c-1", "iPhone 18 Pro", "feature", "iPhone 18 Pro",
                              (), text, ())
        assert not catalog_claim_is_lineup(GOAL, claim), text


def test_catalog_relevance_accepts_named_offered_product():
    for text in [
        "Apple bietet das iPhone 18 Pro offiziell an.",
        "Das iPhone 18 Pro ist in der aktuellen Modellpalette aufgeführt.",
        "Im aktuellen Angebot steht das iPhone 18 Pro.",
    ]:
        claim = SemanticClaim("c-1", "iPhone 18 Pro", "catalog",
                              "iPhone 18 Pro", (), text, ())
        assert catalog_claim_is_lineup(GOAL, claim), text


def test_catalog_relevance_does_not_change_unrelated_technical_answers():
    claim = SemanticClaim("c-1", "PostgreSQL 17", "release",
                          "2024", (), "PostgreSQL 17 erschien 2024.", ())
    assert catalog_claim_is_lineup("Wann erschien PostgreSQL 17?", claim)


def test_native_like_off_topic_eight_claims_abstain_without_verifier():
    bundle = build_evidence(observed(), goal=GOAL)
    pid = next(f.id for f in bundle.facts if "-catalog-" in f.id)
    features = [
        "Das iPhone 18 Pro hat eine 48 MP Kamera.",
        "Das iPhone 18 Pro bietet variable Blende.",
        "Das iPhone Duo unterstützt On-Device KI.",
        "Das iPhone Duo filmt in Dolby Vision.",
        "Das iPhone 17 schützt seine Daten.",
        "Das iPhone 16 hat ein stabiles Glas.",
        "Das iPhone 17e empfängt Satellitensignale.",
        "Das iPhone Air unterstützt ein modernes Betriebssystem.",
    ]
    claims = [
        make_claim(statement, subject="iPhone 18 Pro",
                   value="iPhone 18 Pro", passage_ids=(pid,))
        for statement in features
    ]
    llm, calls = scripted({"claims": claims})
    answer = synthesize_verified_evidence(GOAL, observed(), llm)
    assert answer.audit["verified_supported_count"] == 0
    assert len(calls) == 1
    assert answer.audit["error_status"] == "off_topic_catalog_candidates"


def test_catalog_model_list_can_be_verified_from_anchored_source_passage():
    bundle = build_evidence(observed(), goal=GOAL)
    pid = next(f.id for f in bundle.facts if "-catalog-" in f.id)
    name = make_claim("Apple bietet das iPhone 18 Pro offiziell an.",
                      passage_ids=(pid,))
    llm, calls = scripted(
        {"claims": [name]},
        {"claims": [{"id": "c-1", "status": "supported",
                     "reason": "Produkt und Kaufen stehen zusammen in Modellübersicht.",
                     "passage_ids": [pid]}]},
    )
    answer = synthesize_verified_evidence(GOAL, observed(), llm)
    assert answer.audit["verified_supported_count"] == 1
    assert "Apple bietet das iPhone 18 Pro offiziell an." in str(answer)
    assert URL in str(answer)
    assert len(calls) == 2
