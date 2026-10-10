"""Deterministic evidence-audit regression checks."""
import unittest
from agent.claim_validation import audit_numerical_claims, gate_numerical_claims
from agent.prompts import agent_v2_final_answer

URL = "https://example.org/launch"
ARTICLE = "A product launched on 12.08.2026 and was priced at 999 €. " * 5


def fetched(text=ARTICLE):
    return [{"action": "fetch_url", "status": "completed",
             "result": {"ok": True, "url": URL, "text": text}}]


class ClaimValidationTests(unittest.TestCase):
    def test_grounded_number_has_no_warning(self):
        self.assertEqual(gate_numerical_claims("Preis: 999 €.", fetched()),
                         "Preis: 999 €.")

    def test_unsupported_price_is_flagged(self):
        result = gate_numerical_claims("Preis: 1599 €.", fetched())
        self.assertIn("nicht verifiziert", result)
        self.assertIn("1599 €", result)

    def test_unsupported_date_is_flagged(self):
        audit = audit_numerical_claims("Termin: 13.08.2026.", fetched())
        self.assertEqual(audit["unverified"], ["13.08.2026"])

    def test_search_only_is_not_verification(self):
        audit = audit_numerical_claims(
            "1599 €", [{"action": "web_search", "status": "completed",
                        "result": {"results": [{"url": URL}]}}])
        self.assertFalse(audit["checked"])

    def test_failed_fetch_is_ignored(self):
        audit = audit_numerical_claims(
            "1599 €", [{"action": "fetch_url", "status": "completed",
                        "result": {"ok": False, "url": URL, "text": ARTICLE}}])
        self.assertFalse(audit["checked"])

    def test_final_answer_integration(self):
        answer = agent_v2_final_answer(
            "Wie teuer ist das Produkt?", fetched(),
            observed_agent_llm=lambda *a, **k: "Es kostet 1599 €."
        )
        self.assertIn("nicht verifiziert", answer)

    def test_simple_math_unaffected(self):
        answer = agent_v2_final_answer(
            "Was ist 17 × 23?", [],
            observed_agent_llm=lambda *a, **k: "391"
        )
        self.assertEqual(answer, "391")


if __name__ == "__main__":
    unittest.main()
