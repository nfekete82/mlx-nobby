"""Web planning context keeps URLs while bounding large fetched pages."""
import unittest
from agent.planning_context import compact_web_planning


class PlanningContextTests(unittest.TestCase):
    def test_fetch_text_is_bounded_and_original_unmodified(self):
        source = {"action": "fetch_url", "status": "completed",
                  "query": "https://www.apple.com/de/iphone/",
                  "result": {"ok": True, "text": "abc" * 20000}}
        shortened = compact_web_planning([source])[0]
        self.assertEqual(len(shortened["result"]["text"]), 1800)
        self.assertEqual(shortened["query"], source["query"])
        self.assertEqual(len(source["result"]["text"]), 60000)

    def test_search_urls_retained(self):
        source = {"action": "search_web", "status": "completed",
                  "result": {"results": [{"url": "https://apple.com/news",
                                          "title": "Apple News", "snippet": "X" * 600}]}}
        result = compact_web_planning([source])[0]
        self.assertEqual(result["result"]["results"][0]["url"], "https://apple.com/news")
        self.assertEqual(len(result["result"]["results"][0]["snippet"]), 300)

    def test_release_date_near_end_is_kept(self):
        article = ("Allgemeine Beschreibung. " * 300
                   + "\nVorbestellung ab 16. Oktober 2026, erhältlich ab 23. Oktober 2026.")
        original = {"action": "fetch_url", "status": "completed",
                    "result": {"ok": True, "text": article}}
        compact = compact_web_planning([original])[0]["result"]["text"]
        self.assertIn("23. Oktober 2026", compact)
        self.assertIn("16. Oktober 2026", compact)
        self.assertLess(len(compact), 4500)
        self.assertEqual(original["result"]["text"], article)

    def test_unrelated_late_text_not_copied(self):
        article = "x" * 10000 + "\nBeliebiger Kommentar ohne Termin."
        result = compact_web_planning([{"action": "fetch_url",
                                        "result": {"text": article}}])[0]
        self.assertEqual(len(result["result"]["text"]), 1800)

    def test_single_line_late_availability_and_truncation_are_explicit(self):
        text = "Background " * 1000 + "Pixel 12 pre-order October 16, 2026, available October 23, 2026."
        result = compact_web_planning([{"action": "fetch_url", "result": {"text": text}}])[0]["result"]
        self.assertIn("October 23, 2026", result["text"])
        self.assertTrue(result["text_truncated"])
        self.assertEqual(result["original_text_chars"], len(text))

    def test_late_search_snippet_date_is_kept(self):
        snippet = "Background " * 100 + "Erhältlich ab 2026-10-23."
        result = compact_web_planning([{"action": "search_web", "result": {
            "results": [{"url": "https://example.org", "snippet": snippet}]}}])[0]
        self.assertIn("2026-10-23", result["result"]["results"][0]["snippet"])

    def test_official_availability_dates_without_repeated_year_are_preserved(self):
        text = "Pressemitteilung 1. September 2026. " + "Background " * 1000 + (
            "Es kann ab Freitag, 16. Oktober vorbestellt werden und ist ab Freitag, 23. Oktober erhältlich.")
        result = compact_web_planning([{"action": "fetch_url", "result": {"text": text}}])[0]["result"]
        self.assertIn("16. Oktober", result["text"])
        self.assertIn("23. Oktober", result["text"])
        self.assertIn("September 2026", result["text"])

    def test_coding_observation_preserved(self):
        source = {"action": "code_read", "result": {"content": "important" * 3000}}
        self.assertIs(compact_web_planning([source])[0], source)


if __name__ == "__main__":
    unittest.main()
