"""Malformed verifier output must not be mistaken for source disagreement."""
from agent.v15_run_inspection import inspect_case


def test_invalid_verifier_has_distinct_diagnostic():
    row = {
        "id": "CD09", "question": "Latest stable Python version?",
        "elapsed_ms": 15000.0, "category": "software_current",
        "response": {
            "status": "completed", "answer": "Keine ausreichend belegten Angaben.",
            "steps": [{
                "action": "fetch_url", "status": "completed",
                "result": {"ok": True, "url": "https://docs.python.org/3/",
                           "text": "Python 3 documentation"}
            }],
            "evidence": {
                "verified_supported_count": 0, "error_status": None,
                "claims": [{"id": "c-1", "status": "not_checked",
                            "decision_origin": "invalid_response",
                            "reason": "Keine gültige Verifikation vorhanden."}]
            }
        }
    }
    report = inspect_case(row)
    assert report["stage_hint"] == "verifier_invalid_response"
    assert report["supported_count"] == 0


def test_insufficient_evidence_remains_separate():
    row = {
        "id": "CD01", "elapsed_ms": 1000.0, "category": "products",
        "response": {
            "status": "completed", "answer": "Nicht belegt.",
            "steps": [{
                "action": "fetch_url", "status": "completed",
                "result": {"ok": True, "url": "https://example.org/page",
                           "text": "Not a product lineup"}
            }],
            "evidence": {
                "verified_supported_count": 0, "error_status": None,
                "claims": [{"id": "c-1", "status": "insufficient_evidence",
                            "decision_origin": "model",
                            "reason": "Nicht belegt."}]
            }
        }
    }
    assert inspect_case(row)["stage_hint"] == "candidate_verification_or_abstention"
