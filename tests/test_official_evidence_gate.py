"""An official research failure cannot return an unsupported sale claim."""
from agent.official_evidence_gate import gate_unverified_official_answer

GOAL = "Welche iPhones bietet Apple offiziell aktuell an?"
CLAIM = "Das iPhone Duo ist bereits erhältlich und unabhängig bestätigt."


def test_failed_search_suppresses_false_confirmation():
    answer = gate_unverified_official_answer(
        CLAIM, GOAL, [{"action": "search_web", "status": "completed",
                       "result": {"ok": True, "results": []}}])
    assert "bereits erhältlich" not in answer
    assert "nicht anhand tatsächlich geladener" in answer


def test_unreadable_fetch_also_suppresses_claim():
    answer = gate_unverified_official_answer(
        CLAIM, GOAL, [{"action": "fetch_url", "status": "completed",
                       "result": {"ok": True, "url": "https://apple.com/news", "text": ""}}])
    assert "unabhängig bestätigt" not in answer


def test_valid_article_keeps_answer_for_other_gates():
    observations = [{"action": "fetch_url", "status": "completed",
                     "result": {"ok": True, "url": "https://apple.com/news",
                                "text": "Official product listing. " * 10}}]
    assert gate_unverified_official_answer(CLAIM, GOAL, observations) == CLAIM


def test_non_official_or_non_web_request_is_untouched():
    search = [{"action": "search_web", "status": "completed", "result": {}}]
    assert gate_unverified_official_answer(CLAIM, "Schreibe einen Roman", search) == CLAIM
    assert gate_unverified_official_answer(CLAIM, GOAL, []) == CLAIM
