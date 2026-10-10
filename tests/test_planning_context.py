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

    def test_coding_observation_preserved(self):
        source = {"action": "code_read", "result": {"content": "important" * 3000}}
        self.assertIs(compact_web_planning([source])[0], source)


if __name__ == "__main__":
    unittest.main()
