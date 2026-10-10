"""Context matching avoids treating unrelated product prices as evidence."""
import unittest
from agent.claim_context import matches_claim
from agent.claim_validation import gate_numerical_claims

URL = "https://example.org/phones"

def fetched(text):
    return [{"action": "fetch_url", "status": "completed",
             "result": {"ok": True, "url": URL, "text": text}}]

class ContextEvidenceTests(unittest.TestCase):
    def test_wrong_product_price_is_not_evidence(self):
        article = ("Pixel 11 kostet 999 €. " + "Informationen zur Technik. " * 10
                   + "Galaxy S30 kostet 1599 €. " + "Weitere Einzelheiten. " * 10)
        result = gate_numerical_claims("Pixel 11 kostet 1599 €.", fetched(article))
        self.assertIn("nicht verifiziert", result)

    def test_right_product_price_remains(self):
        article = "Pixel 11 kostet 999 €. " * 12
        result = gate_numerical_claims("Pixel 11 kostet 999 €.", fetched(article))
        self.assertNotIn("nicht verifiziert", result)

    def test_source_without_product_name_is_insufficient(self):
        self.assertFalse(matches_claim("999 €", "Pixel 11 kostet 999 €.",
                                       [(URL, "Ein anderes Gerät kostet 999 €.")]))

if __name__ == "__main__":
    unittest.main()
