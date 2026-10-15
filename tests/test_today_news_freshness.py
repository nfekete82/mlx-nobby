"""Tests for explicitly same-day news evidence filters (fully offline)."""
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs

from agent.search_freshness import (
    filter_today_news,
    publication_time,
    requires_today_news,
)
from backend.web_research import retrieve_web_research
from tests.test_web_research import FakeResponse


class TodayNewsTest(TestCase):
    NOW = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)

    def test_only_explicit_same_day_news_uses_strict_filter(self):
        self.assertTrue(requires_today_news("Gib mir alle wichtigen News von heute zusammengefasst"))
        self.assertTrue(requires_today_news("Nachrichten heute"))
        self.assertFalse(requires_today_news("Was gibt es Neues bei NVIDIA?"))
        self.assertFalse(requires_today_news("Wie wird das Wetter heute?"))
        self.assertFalse(requires_today_news("News aus dem Jahr 2025"))

    def test_iso_rfc_missing_old_and_future_dates(self):
        entries = [
            {"title": "old", "published_date": "Wed, 14 Oct 2026 19:00:00 GMT"},
            {"title": "new-rfc", "published_date": "Thu, 15 Oct 2026 07:00:00 GMT"},
            {"title": "new-iso", "published_date": "2026-10-15T07:45:00+00:00"},
            {"title": "new-after-midnight-local", "published_date": "Wed, 14 Oct 2026 22:30:00 GMT"},
            {"title": "future", "published_date": "Thu, 15 Oct 2026 18:00:00 GMT"},
            {"title": "missing", "published_date": None},
            {"title": "invalid", "published_date": "last week"},
        ]
        self.assertEqual(
            [r["title"] for r in filter_today_news(entries, now=self.NOW)],
            ["new-rfc", "new-iso", "new-after-midnight-local"],
        )
        self.assertIsNone(publication_time("Thu, 15 Oct 2026 08:00:00"))

    def test_backend_research_does_not_present_old_sources_as_today(self):
        rss = ('<rss><channel><item><title>Stale April item</title>'
               '<link>https://example.org/april</link>'
               '<pubDate>Thu, 30 Apr 2026 10:00:00 GMT</pubDate></item>'
               '<item><title>Verified today item</title>'
               '<link>https://example.org/today</link>'
               '<pubDate>Thu, 15 Oct 2026 07:15:00 GMT</pubDate></item>'
               '<item><title>Undated item</title>'
               '<link>https://example.org/no-date</link></item>'
               '</channel></rss>')
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            return FakeResponse(rss)
        result = retrieve_web_research(
            "Gib mir alle wichtigen News von heute zusammengefasst",
            opener=opener, now=self.NOW,
        )
        self.assertIn("Verified today item", result)
        self.assertNotIn("Stale April item", result)
        self.assertNotIn("Undated item", result)
        self.assertIn("when%3A1d", calls[0])

    def test_backend_research_reports_no_verified_headlines(self):
        rss = ('<rss><channel><item><title>Old news</title>'
               '<link>https://example.org/old</link>'
               '<pubDate>Thu, 30 Apr 2026 10:00:00 GMT</pubDate></item>'
               '</channel></rss>')
        result = retrieve_web_research(
            "Alle News von heute",
            opener=lambda _request, timeout: FakeResponse(rss),
            now=self.NOW,
        )
        self.assertIn("OHNE VERIFIZIERBARE ERGEBNISSE", result)
        self.assertNotIn("Old news", result)

    def test_agent_searxng_drops_stale_and_undated_news(self):
        from agent.app import searxng_search_results
        payload = {
            "results": [
                {"title": "Old", "url": "https://example.org/old",
                 "publishedDate": "2026-04-30T08:00:00+00:00"},
                {"title": "Undated", "url": "https://example.org/undated"},
                {"title": "Current", "url": "https://example.org/current",
                 "publishedDate": format_datetime(datetime.now(timezone.utc))},
            ],
            "unresponsive_engines": [],
        }
        recorded = []
        def search(_base, params):
            recorded.append(parse_qs(params))
            return payload, [{"status": "available"}]
        with patch("agent.app.request_searxng", side_effect=search), \
             patch("agent.app.web_url_is_safe", return_value=True):
            result = searxng_search_results("Wichtige News von heute")
        self.assertEqual(recorded[0]["time_range"], ["day"])
        self.assertEqual([item["title"] for item in result["results"]], ["Current"])
        self.assertEqual(result["freshness_status"], "verified_today_only")

    def test_undated_today_news_fall_back_without_fabrication(self):
        from agent.app import searxng_search_results
        with patch("agent.app.request_searxng", return_value=(
            {"results": [{"title": "Undated", "url": "https://example.org/x"}]},
            [{"status": "available"}],
        )), patch("agent.app.web_url_is_safe", return_value=True), \
             patch("agent.app._fallback_public_search", return_value={
                 "results": [], "count": 0,
                 "provider_status": "no_verified_today_news",
             }):
            result = searxng_search_results("News von heute")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["provider_status"], "no_verified_today_news")
