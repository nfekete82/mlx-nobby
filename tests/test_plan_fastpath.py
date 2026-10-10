"""Safety and selection regression tests for deterministic planning."""
import unittest
from agent.plan_fastpath import choose_official_followup

URL = "https://www.apple.com/de/newsroom/2026/09/phone/"
SEARCH = {"action": "search_web", "status": "completed",
          "result": {"results": [
              {"url": URL, "title": "Offizielle Herstellerinformation"},
              {"url": "https://example.com/article", "title": "Blog commentary"},
          ]}}


class PlanningFastpathTests(unittest.TestCase):
    def test_picks_official_article(self):
        result = choose_official_followup("Welche iPhones bietet Apple offiziell an?", [SEARCH])
        self.assertEqual(result["action"], "fetch_url")
        self.assertEqual(result["query"], URL)

    def test_apple_domain_without_official_title(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": URL, "title": "iPhone Produktneuheiten"}]}}
        result = choose_official_followup("Welche aktuellen iPhone-Modelle bietet Apple offiziell an?", [search])
        self.assertEqual(result["query"], URL)

    def test_similar_lookalike_domain_not_trusted(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": "https://apple.com.example.org/news", "title": "iPhone Neuheiten"}]}}
        self.assertIsNone(choose_official_followup("Welche iPhones bietet Apple offiziell an?", [search]))

    def test_skips_already_fetched(self):
        fetched = {"action": "fetch_url", "status": "completed", "query": URL}
        self.assertIsNone(choose_official_followup("Offizielle Modelle?", [SEARCH, fetched]))

    def test_does_not_trigger_for_nonofficial_question(self):
        self.assertIsNone(choose_official_followup("Welche Modelle gibt es?", [SEARCH]))

    def test_rejects_untrusted_urls_and_root_pages(self):
        bad = {"action": "search_web", "status": "completed",
               "result": {"results": [
                   {"url": "http://example.org/a", "title": "official"},
                   {"url": "https://example.org/", "title": "official"},
                   {"url": "https://user:pass@example.org/a", "title": "official"}]}}
        self.assertIsNone(choose_official_followup("Offizielle Modelle?", [bad]))

    def test_skips_search_failures(self):
        failed = dict(SEARCH, status="failed")
        self.assertIsNone(choose_official_followup("Offizielle Modelle?", [failed]))


if __name__ == "__main__":
    unittest.main()
