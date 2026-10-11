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



class OfficialCatalogFollowupTests(unittest.TestCase):
    def setUp(self):
        from agent.plan_fastpath import (
            official_catalog_goal, choose_official_catalog_refinement,
            insufficient_catalog_sources,
        )
        self.catalog = official_catalog_goal
        self.refine = choose_official_catalog_refinement
        self.insufficient = insufficient_catalog_sources
        self.goal = "Welche aktuellen iPhone-Modelle bietet Apple offiziell an?"

    def search(self, *urls, provider="SearXNG"):
        return {"action": "search_web", "status": "completed",
                "result": {"provider": provider, "count": len(urls),
                           "results": [{"url": u, "title": u} for u in urls]}}

    def fetched(self, url, *, ok=True):
        return {"action": "fetch_url", "status": "completed",
                "query": url,
                "result": {"ok": ok, "url": url,
                           "text": "Apple iPhone product details. " * 25}}

    def test_apple_official_lineup_intent(self):
        self.assertTrue(self.catalog(self.goal))
        self.assertFalse(self.catalog("Wann wurde das iPhone 15 offiziell vorgestellt?"))
        self.assertFalse(self.catalog("Was kostet das iPhone?"))

    def test_locale_root_is_not_a_model_specific_source(self):
        hits = self.search("https://www.apple.com/de/",
                           "https://www.apple.com/de/iphone/")
        self.assertIsNone(choose_official_followup(self.goal, [hits]))
        self.assertTrue(self.insufficient(self.goal,
                                          [hits, self.fetched("https://www.apple.com/de/")]))
        self.assertTrue(self.insufficient(self.goal,
                                          [hits, self.fetched("https://www.apple.com/de/iphone/")]))

    def test_refines_once_after_generic_landing_results(self):
        hits = self.search("https://www.apple.com/de/",
                           "https://www.apple.com/de/iphone/")
        decision = self.refine(self.goal, [hits])
        self.assertEqual(decision["action"], "search_web")
        self.assertIn("site:apple.com", decision["query"])
        self.assertIn("iphone", decision["query"].lower())
        self.assertIsNone(self.refine(self.goal, [hits, hits]))
        self.assertIsNone(self.refine(self.goal,
                                     [self.search("https://www.apple.com/de/", provider="Google News RSS (fallback)")]))
        self.assertIsNone(self.refine(self.goal, [self.search(provider="SearXNG")]))

    def test_fetches_real_topic_detail_from_results(self):
        page = "https://www.apple.com/de/shop/buy-iphone/example-model"
        hits = self.search("https://www.apple.com/de/", page)
        answer = choose_official_followup(self.goal, [hits])
        self.assertEqual(answer["query"], page)
        self.assertIsNone(self.refine(self.goal, [hits]))

    def test_relevant_product_beats_unrelated_newsroom_article(self):
        relevant = "https://www.apple.com/de/shop/buy-iphone/iphone-example"
        unrelated = "https://www.apple.com/newsroom/2026/10/mac-example/"
        hits = self.search(unrelated, relevant)
        self.assertEqual(choose_official_followup(self.goal, [hits])["query"], relevant)

    def test_good_source_allows_early_answer_and_generic_does_not(self):
        article = "https://www.apple.com/newsroom/2026/10/iphone-example/"
        root = "https://www.apple.com/de/"
        self.assertFalse(self.insufficient(self.goal, [self.fetched(article)]))
        self.assertFalse(self.insufficient(self.goal,
                                           [self.fetched(root), self.fetched(article)]))
        self.assertFalse(self.insufficient("Apple Gründungsgeschichte", [self.fetched(root)]))

    def test_no_authority_bypass_with_lookalikes_or_rss(self):
        hits = self.search("https://apple.com.example.org/iphone/iphone-19/",
                           "https://news.google.com/rss/articles/example")
        self.assertIsNone(choose_official_followup(self.goal, [hits]))
        self.assertIsNotNone(self.refine(self.goal, [hits]))

    def test_actual_observed_search_results_skip_unrelated_support_and_refine(self):
        # This is the real source-path failure from the 11.1s native run.
        hits = self.search(
            "https://www.apple.com/de/",
            "https://www.apple.com/de/store",
            "https://appleid.apple.com/de-de/",
            "https://www.icloud.com/",
            "https://en.wikipedia.org/wiki/Apple_Inc",
            "https://support.apple.com/de-de",
        )
        self.assertIsNone(choose_official_followup(self.goal, [hits]))
        decision = self.refine(self.goal, [hits])
        self.assertIsNotNone(decision)
        self.assertEqual(decision["action"], "search_web")
        self.assertIn("site:apple.com", decision["query"])
        self.assertTrue(self.insufficient(self.goal, [
            hits, self.fetched("https://support.apple.com/de-de"),
        ]))

    def test_slashless_locale_roots_are_not_credible_catalog_pages(self):
        from agent.plan_fastpath import _general_landing_page
        for url in (
            "https://www.apple.com/de", "https://www.apple.com/de/",
            "https://support.apple.com/de-de", "https://appleid.apple.com/de-de/",
            "https://www.apple.com/", "https://www.apple.com/de/store",
        ):
            self.assertTrue(_general_landing_page(url), url)

    def test_official_support_cannot_be_used_even_when_title_mentions_product(self):
        hits = {"action": "search_web", "status": "completed",
                "result": {"provider": "SearXNG", "results": [
                    {"url": "https://support.apple.com/de-de/iphone",
                     "title": "iPhone Hilfe und Support"},
                    {"url": "https://www.apple.com/de/shop/buy-iphone/model",
                     "title": "iPhone kaufen"},
                ]}}
        self.assertEqual(choose_official_followup(self.goal, [hits])["query"],
                         "https://www.apple.com/de/shop/buy-iphone/model")

    def test_company_name_alone_is_not_enough_for_specific_catalog(self):
        hits = {"action": "search_web", "status": "completed",
                "result": {"provider": "SearXNG", "results": [
                    {"url": "https://www.apple.com/newsroom/2026/10/macbook-only/",
                     "title": "Apple officially presents new Macs"},
                ]}}
        self.assertIsNone(choose_official_followup(self.goal, [hits]))

    def test_same_security_rules_apply_to_different_manufacturers(self):
        goal = "Which current Pixel models does Google officially offer?"
        hits = {"action": "search_web", "status": "completed",
                "result": {"provider": "SearXNG", "results": [
                    {"url": "https://support.google.com/pixelphone/answer/test",
                     "title": "Pixel phone help"},
                    {"url": "https://store.google.com/product/pixel_example",
                     "title": "Pixel phone official store"},
                ]}}
        self.assertEqual(choose_official_followup(goal, [hits])["query"],
                         "https://store.google.com/product/pixel_example")

    def test_no_repeated_fetch_of_already_fetched_article(self):
        article = "https://www.apple.com/de/shop/buy-iphone/example"
        hits = self.search("https://www.apple.com/de/", article)
        self.assertIsNone(choose_official_followup(self.goal, [hits, self.fetched(article)]))


if __name__ == "__main__":
    unittest.main()
