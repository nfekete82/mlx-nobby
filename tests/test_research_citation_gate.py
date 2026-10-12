"""Only successfully fetched article URLs may be cited in a research answer."""
import unittest
from agent.prompts import enforce_research_citations

class CitationGateTests(unittest.TestCase):
    def test_bare_domain_upgraded_to_the_single_fetched_article(self):
        observations = [{"action":"fetch_url","status":"completed",
                         "result":{"ok":True,"url":"https://www.adac.de/elektroauto/neuheiten"}}]
        result = enforce_research_citations("1. Modell A – Quelle: ADAC.", observations)
        self.assertIn("https://www.adac.de/elektroauto/neuheiten", result)
        self.assertNotIn("https://adac.de/", result)

    def test_search_only_cannot_claim_confirmed_source(self):
        observations = [{"action":"web_search","status":"completed",
                         "result":{"ok":True,"url":"https://example.org/article"}}]
        result = enforce_research_citations("1. Modell A", observations)
        self.assertIn("keine vollständig geladenen Artikelquellen", result)

    def test_unsupported_item_is_omitted(self):
        observations = [{"action":"fetch_url","status":"completed",
                         "result":{"ok":True,"url":"https://example.org/article"}}]
        result = enforce_research_citations(
            "1. Modell A ([Quelle](https://example.org/article))\n2. Modell B – Quelle: unverified.net",
            observations)
        self.assertIn("Modell A", result)
        self.assertNotIn("Modell B", result)

if __name__ == "__main__":
    unittest.main()
