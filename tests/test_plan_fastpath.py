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

    def test_official_words_cannot_promote_an_aggregator_or_lookalike(self):
        for url in ("https://news.google.com/rss/articles/123", "https://apple.com.example.org/news", "https://[bad/news"):
            search = {"action": "search_web", "status": "completed", "result": {
                "results": [{"url": url, "title": "Offizieller Apple Herstellerbericht"}]}}
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


    def test_prefers_specific_apple_newsroom_article_over_iphone_overview(self):
        article = "https://www.apple.com/newsroom/2026/09/new-iphone-launch/"
        landing = "https://www.apple.com/iphone/"
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": landing, "title": "iPhone - Apple"},
                      {"url": article, "title": "New iPhone announcement"},
                  ]}}
        result = choose_official_followup("Welche Apple Produkte sind offiziell erhältlich?", [search])
        self.assertEqual(result["query"], article)

    def test_skips_news_aggregator_even_when_marked_official(self):
        apple = "https://www.apple.com/newsroom/2026/09/new-mac/"
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": "https://news.google.com/rss/articles/abc",
                       "title": "Official Apple iPhone"},
                      {"url": apple, "title": "Mac from Apple"},
                  ]}}
        result = choose_official_followup("Apple offiziell", [search])
        self.assertEqual(result["query"], apple)

    def test_no_official_source_is_not_fabricated(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": "https://news.google.com/rss/articles/abc",
                       "title": "Official Apple iPhone"},
                      {"url": "https://other-site.example/news/apple",
                       "title": "Official Apple iPhone"},
                  ]}}
        self.assertIsNone(choose_official_followup("Apple offiziell", [search]))

    def test_does_not_promote_rss_wrapper_even_on_official_host(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": "https://www.apple.com/newsroom/2026/09/foo",
                       "title": "Apple press", "source_type": "rss_search_entry"},
                  ]}}
        self.assertIsNone(choose_official_followup("Apple offiziell", [search]))

    def test_chooses_dedicated_store_page_ahead_of_generic_overview(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [
                      {"url": "https://www.apple.com/iphone/", "title": "iPhone"},
                      {"url": "https://www.apple.com/shop/buy-iphone/iphone-18",
                       "title": "Buy iPhone 18"},
                  ]}}
        result = choose_official_followup("Apple iPhone offiziell erhältlich", [search])
        self.assertEqual(result["query"], "https://www.apple.com/shop/buy-iphone/iphone-18")

    def test_non_official_intent_does_not_trigger_fastpath(self):
        search = {"action": "search_web", "status": "completed",
                  "result": {"results": [{"url": "https://www.apple.com/newsroom/2026/09/foo",
                                           "title": "Apple press"}]}}
        self.assertIsNone(choose_official_followup("Welche iPhones bietet Apple an?", [search]))


if __name__ == "__main__":
    unittest.main()
