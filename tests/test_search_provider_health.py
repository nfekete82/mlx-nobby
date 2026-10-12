"""Offline provider degradation, source retrieval and request reuse checks."""
from email.message import Message
import io
import json
import unittest
from unittest.mock import patch
import urllib.error

from agent.app import searxng_search_results, fetch_web_page, _fallback_public_search
from agent.research_cache import request_research_cache, reuse_research_observation


class Response(io.BytesIO):
    def __init__(self, payload, content_type="application/json"):
        super().__init__(payload.encode() if isinstance(payload, str) else payload)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class ProviderHealthTests(unittest.TestCase):
    def test_engine_failure_classification_and_failed_fallback_remain_visible(self):
        payload = {"results": [], "unresponsive_engines": [
            ["google", "too many requests"], ["startpage", "Suspended: CAPTCHA"],
            ["duckduckgo", "Suspended: access denied"]]}
        with patch.dict("os.environ", {"SEARXNG_FALLBACK_URLS": ""}), \
             patch("urllib.request.urlopen", return_value=Response(json.dumps(payload))), \
             patch("agent.app._fallback_public_search", return_value={"results": [], "provider_status": "unavailable"}):
            result = searxng_search_results("public query")
        self.assertEqual(result["primary_provider_status"], "degraded")
        self.assertEqual([engine["status"] for engine in result["unresponsive_engines"]],
                         ["rate_limited", "captcha", "access_denied"])
        self.assertEqual([item["status"] for item in result["provider_attempts"]], ["degraded", "unavailable"])

    def test_explicit_secondary_provider_used_after_rate_limit(self):
        success = {"results": [{"title": "Public", "url": "https://example.org/news"}]}
        with patch.dict("os.environ", {"SEARXNG_FALLBACK_URLS": "http://127.0.0.1:8082"}), \
             patch("urllib.request.urlopen", side_effect=[urllib.error.HTTPError("url", 429, "blocked", {}, None), Response(json.dumps(success))]) as opener, \
             patch("agent.app.web_url_is_safe", return_value=True):
            result = searxng_search_results("public query")
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(result["count"], 1)
        self.assertEqual([item["status"] for item in result["provider_attempts"]], ["rate_limited", "available"])

    def test_invalid_provider_schema_falls_back_without_crash(self):
        for payload in ([], {"results": None}, {"results": [], "unresponsive_engines": None}):
            with self.subTest(payload=payload), \
                 patch.dict("os.environ", {"SEARXNG_FALLBACK_URLS": ""}), \
                 patch("urllib.request.urlopen", return_value=Response(json.dumps(payload))), \
                 patch("agent.app._fallback_public_search", return_value={"results": []}):
                result = searxng_search_results("public query")
            self.assertEqual(result["provider_attempts"][0]["status"], "invalid_response")

    def test_http_200_captcha_page_is_not_a_loaded_article(self):
        page = "Verify you are human. " + "Challenge information. " * 50
        with patch("agent.app.web_url_is_safe", return_value=True), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response(page, "text/html")
            result = fetch_web_page("https://example.org/news")
        self.assertFalse(result["ok"])
        self.assertEqual(result["retrieval_status"], "captcha")
        self.assertNotIn("text", result)

    def test_private_redirect_is_still_blocked(self):
        redirect = urllib.error.HTTPError("url", 302, "redirect", {"Location": "http://127.0.0.1/admin"}, None)
        with patch("agent.app.web_url_is_safe", side_effect=[True, True, False]), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = redirect
            result = fetch_web_page("https://example.org/news")
        self.assertFalse(result["ok"])
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_rss_entries_do_not_claim_loaded_article_evidence(self):
        rss = "<rss><channel><item><title>News</title><link>https://news.google.com/rss/articles/id</link></item></channel></rss>"
        with patch.dict("os.environ", {"MLX_PUBLIC_SEARCH_FALLBACK": "1"}), \
             patch("urllib.request.urlopen", return_value=Response(rss)), \
             patch("agent.app.web_url_is_safe", return_value=True):
            result = _fallback_public_search("query")
        self.assertFalse(result["results"][0]["article_loaded"])
        self.assertEqual(result["results"][0]["source_type"], "rss_search_entry")

    def test_public_fallback_can_be_disabled_without_network(self):
        with patch.dict("os.environ", {"MLX_PUBLIC_SEARCH_FALLBACK": "0"}), \
             patch("urllib.request.urlopen") as opener:
            result = _fallback_public_search("query")
        opener.assert_not_called()
        self.assertEqual(result["provider_status"], "disabled")

    def test_unsuccessful_identical_query_reused_only_within_request(self):
        with patch("agent.app.request_searxng", return_value=(None, [{"status": "timeout"}])) as provider, \
             patch("agent.app._fallback_public_search", return_value={"results": [], "count": 0}):
            with request_research_cache():
                first = searxng_search_results("query")
                first["results"].append({"title": "mutated"})
                second = searxng_search_results("query")
                self.assertEqual(second["results"], [])
                self.assertTrue(second["reused_observation"])
            with request_research_cache():
                third = searxng_search_results("query")
        self.assertEqual(provider.call_count, 2)
        self.assertNotIn("reused_observation", third)

    def test_fetch_success_reused_and_offset_distinguished(self):
        with patch("agent.app.web_url_is_safe", return_value=True), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = [Response("A" * 2000, "text/plain") for _ in range(2)]
            with request_research_cache():
                first = fetch_web_page("https://example.org/news", offset=0)
                repeated = fetch_web_page("https://example.org/news", offset=0)
                next_chunk = fetch_web_page("https://example.org/news", offset=1000)
        self.assertEqual(opener.return_value.open.call_count, 2)
        self.assertTrue(first["ok"] and repeated["ok"] and next_chunk["ok"])
        self.assertEqual(next_chunk["offset"], 1000)

    def test_cache_accepts_equivalent_arguments_and_is_bounded(self):
        calls = []
        @reuse_research_observation
        def adapter(query, limit=8):
            calls.append(query)
            return {"text": query}
        with request_research_cache():
            adapter("query")
            self.assertTrue(adapter(query="query", limit=8)["reused_observation"])
            adapter("x" * 512_001)
            adapter("x" * 512_001)
        self.assertEqual(len(calls), 3)

    def test_cache_scope_cleanup_on_exception(self):
        calls = []
        @reuse_research_observation
        def adapter(query):
            calls.append(query)
            return {"ok": True}
        with self.assertRaises(ValueError):
            with request_research_cache():
                adapter("query")
                raise ValueError("abort")
        self.assertNotIn("reused_observation", adapter("query"))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
