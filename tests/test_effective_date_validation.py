"""Conservative source-effective date validation regression tests."""
import json

from agent.effective_date_validation import effective_date_conflict
from agent.semantic_evidence import synthesize_verified_evidence
from agent.structured_evidence import build_evidence


SOURCE = (
    "At the Governing Council meeting on 10 September 2026, the interest "
    "rate change was decided. The announcement is dated 10 September 2026.\n"
    "Key interest rates\nWith effect from: 16 September 2026\n"
    "Deposit facility: 2.50 percent\n"
    "Main refinancing operations: 2.65 percent.\n"
)


def test_decision_date_is_not_an_effective_date():
    assert effective_date_conflict(
        "Seit dem 10. September 2026 beträgt der Einlagezins 2,50 Prozent.",
        [SOURCE],
    ) == {
        "claimed_date": "2026-09-10",
        "source_effective_date": "2026-09-16",
    }
    assert effective_date_conflict(
        "Seit dem 16. September 2026 beträgt der Einlagezins 2,50 Prozent.",
        [SOURCE],
    ) is None
    assert effective_date_conflict(
        "Am 10. September 2026 hat die EZB entschieden.", [SOURCE]
    ) is None
    assert effective_date_conflict(
        "Seit dem 10. September 2026 gilt der Satz.",
        ["The decision was announced on 10 September 2026."],
    ) is None
    assert effective_date_conflict(
        "Seit dem 10. September 2026 gilt der Satz.",
        [SOURCE + "\nWith effect from: 19 September 2026"],
    ) is None


def test_model_cannot_mark_explicitly_wrong_effective_date_supported():
    url = "https://www.ecb.europa.eu/press/monetary-policy.html"
    source = {"action": "fetch_url", "status": "completed", "query": url,
              "result": {"ok": True, "url": url, "text": SOURCE}}
    goal = "Wie hoch ist der EZB-Einlagezins und seit wann gilt er?"
    passage = build_evidence([source], goal=goal).facts[0].id

    def llm(purpose, prompt, limit):
        if purpose == "agent.extract":
            return json.dumps({"claims": [{
                "subject": "EZB-Einlagezins",
                "predicate": "effective_since",
                "value": "10 September 2026",
                "qualifiers": {},
                "statement": "Seit dem 10. September 2026 gilt der EZB-Einlagezins von 2,50 Prozent.",
                "passage_ids": [passage],
            }]})
        return json.dumps({"claims": [{
            "id": "c-1", "status": "supported",
            "reason": "Die Quelle nennt das Datum",
            "passage_ids": [passage],
        }]})

    result = synthesize_verified_evidence(goal, [source], llm)
    assert result.audit["verified_supported_count"] == 0
    assert result.audit["claims"][0]["status"] == "contradicted"
    assert result.audit["claims"][0]["decision_origin"] == "effective_date_validation"
    assert result.audit["claims"][0]["deterministic_validation"]["effective_date"] == {
        "claimed_date": "2026-09-10",
        "source_effective_date": "2026-09-16",
    }
