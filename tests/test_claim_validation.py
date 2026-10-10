"""Deterministic evidence-audit regression checks."""
import unittest
from agent.claim_validation import audit_numerical_claims, gate_numerical_claims, gate_source_links
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

    def test_linked_price_is_still_a_claim(self):
        audit = audit_numerical_claims("[Preis: 1599 €](https://example.org/launch)", fetched())
        self.assertEqual(audit["unverified"], ["1599 €"])

    def test_named_and_iso_dates_and_prefix_currency_are_checked(self):
        for value in ("23. Oktober 2026", "2026-10-23", "October 23, 2026", "$1599"):
            self.assertEqual(audit_numerical_claims("Termin/Preis: " + value, fetched())["unverified"], [value])

    def test_product_list_checks_each_subject(self):
        text = "Pixel 11 kostet 999 €. " * 15 + "Galaxy S26 kostet 1299 €. " * 15
        audit = audit_numerical_claims("Pixel 11 kostet 999 €.\nGalaxy S26 kostet 999 €.", fetched(text))
        self.assertEqual(audit["unverified"], ["999 €"])

    def test_prices_in_same_sentence_use_their_own_product(self):
        text = "Pixel 11 kostet 999 €. " * 15 + "Galaxy S26 kostet 1299 €. " * 15
        audit = audit_numerical_claims("Pixel 11 kostet 999 €, Galaxy S26 kostet 1299 €.", fetched(text))
        self.assertEqual(audit["unverified"], [])

    def test_prefix_price_excludes_sentence_punctuation(self):
        audit = audit_numerical_claims("Preis: $1599.", fetched())
        self.assertEqual(audit["unverified"], ["$1599"])

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

    def test_invented_citation_is_removed_and_fetched_one_remains(self):
        result = gate_source_links(f"[Quelle]({URL}) und [Phantom](https://fake.example/article).", fetched())
        self.assertIn(URL, result)
        self.assertNotIn("fake.example", result)
        self.assertIn("Linkprüfung", result)

    def test_search_snippets_do_not_establish_evidence(self):
        result = gate_source_links("Das Gerät ist erhältlich.", [])
        self.assertIn("nicht unabhängig bestätigt", result)

    def test_observation_date_is_not_an_unsupported_article_claim(self):
        result = audit_numerical_claims("Stand: 11.10.2026. Preis: 999 €.", fetched())
        self.assertEqual(result["unverified"], [])


if __name__ == "__main__":
    unittest.main()
