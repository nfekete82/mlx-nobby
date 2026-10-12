"""Evidence URLs are taken only from successfully opened article pages."""
import unittest

from agent.prompts import loaded_web_article_urls


class LoadedWebArticlesTests(unittest.TestCase):
    def test_only_loaded_article_links(self):
        observations = [
            {"action": "web_search", "status": "completed",
             "result": {"ok": True, "url": "https://example.org/search-only"}},
            {"action": "fetch_url", "status": "failed",
             "query": "https://example.org/failure", "result": {"ok": False}},
            {"action": "fetch_url", "status": "completed",
             "query": "https://example.org/actual-report",
             "result": {"ok": True, "url": "https://example.org/actual-report"}},
            {"action": "fetch_url", "status": "completed",
             "result": {"ok": True, "url": "https://example.org/"}},
        ]
        self.assertEqual(loaded_web_article_urls(observations), ["https://example.org/actual-report"])


if __name__ == "__main__":
    unittest.main()
