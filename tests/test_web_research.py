"""Offline regression tests for public web search and privacy boundaries."""
import ast
import io
from pathlib import Path
import unittest
from backend.web_research import needs_web_research, retrieve_web_research


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload.encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, amount):
        return self.payload[:amount]


class ResearchTests(unittest.TestCase):
    def test_python_source_parses(self):
        ast.parse((Path(__file__).resolve().parents[1] / "backend" / "web_research.py").read_text())

    def test_public_current_intents(self):
        for query in ["Wer ist aktuell Bundeskanzler?", "Was sind die neuesten Nachrichten?",
                      "Wie teuer ist das neue Elektroauto 2026?"]:
            with self.subTest(query=query):
                self.assertTrue(needs_web_research(query))

    def test_private_and_local_prompts_never_sent(self):
        for query in ["Was ist aktuell in meinem Workspace?", "Wie geht mein Gehalt 2026?",
                      "Prüfe localhost heute", "Was ist aktuell auf crm.dpolg-service.local?",
                      "Was gibt es 2026 im Repository?", "Was ist das Passwort heute?"]:
            with self.subTest(query=query):
                self.assertFalse(needs_web_research(query))
                self.assertEqual(retrieve_web_research(query, opener=lambda *_args, **_kwargs: self.fail("Network accessed")), "")

    def test_public_search_results_include_source_urls(self):
        html = '<a class="result-link" href="https://example.org/article">Ergebnis vom Anbieter</a>'
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?",
            opener=lambda _req, timeout: FakeResponse(html))
        self.assertIn("https://example.org/article", result)
        self.assertIn("Suchtreffer", result)

    def test_redirect_links_are_decoded(self):
        html = '<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fnews">Real headline</a>'
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?",
            opener=lambda _req, timeout: FakeResponse(html))
        self.assertIn("https://example.org/news", result)
        self.assertNotIn("duckduckgo.com/l/", result)

    def test_no_results_are_disclosed(self):
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?",
            opener=lambda _req, timeout: FakeResponse("<html></html>"))
        self.assertIn("OHNE VERIFIZIERBARE ERGEBNISSE", result)

    def test_google_news_fallback_when_lite_has_no_links(self):
        rss = ('<rss><channel><item><title>Elektroauto vorgestellt 2026</title>'
               '<link>https://news.google.com/rss/articles/123</link>'
               '<pubDate>Sat, 10 Oct 2026 12:00:00 GMT</pubDate>'
               '</item></channel></rss>')
        def opener(request, timeout):
            return FakeResponse(rss if "news.google.com" in request.full_url else "<html></html>")
        result = retrieve_web_research("Welche Elektroautos wurden 2026 vorgestellt?", opener=opener)
        self.assertIn("Elektroauto vorgestellt 2026", result)
        self.assertIn("https://news.google.com/rss/articles/123", result)

    def test_compound_borsennews_uses_finance_rss_and_today_filter(self):
        from datetime import datetime, timezone
        from urllib.parse import parse_qs, urlsplit
        rss = ('<rss><channel>'
               '<item><title>GIB Gibraltar News</title>'
               '<link>https://example.org/gib</link>'
               '<pubDate>Thu, 15 Oct 2026 07:00:00 GMT</pubDate></item>'
               '<item><title>DAX und Aktienmärkte steigen</title>'
               '<link>https://example.org/dax</link>'
               '<pubDate>Thu, 15 Oct 2026 07:00:00 GMT</pubDate></item>'
               '<item><title>Aktien von gestern</title>'
               '<link>https://example.org/old</link>'
               '<pubDate>Wed, 14 Oct 2026 07:00:00 GMT</pubDate></item>'
               '</channel></rss>')
        visited = []
        def opener(req, timeout):
            visited.append(req.full_url)
            return FakeResponse(rss)
        output = retrieve_web_research(
            "gib mir alle börsennews von heute",
            opener=opener, now=datetime(2026, 10, 15, 9, tzinfo=timezone.utc))
        params = parse_qs(urlsplit(visited[0]).query)
        self.assertEqual(params["q"], ["Börse Aktienmärkte when:1d"])
        self.assertIn("news.google.com/rss/search", visited[0])
        self.assertIn("DAX und Aktienmärkte", output)
        self.assertNotIn("GIB Gibraltar", output)
        self.assertNotIn("Aktien von gestern", output)

    def test_network_error_not_fabricated(self):
        def offline(_req, timeout):
            raise OSError("offline")
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?", opener=offline)
        self.assertIn("NICHT VERFÜGBAR", result)


if __name__ == "__main__":
    unittest.main()
