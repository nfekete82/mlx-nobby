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

    def test_no_results_are_disclosed(self):
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?",
            opener=lambda _req, timeout: FakeResponse("<html></html>"))
        self.assertIn("OHNE VERIFIZIERBARE ERGEBNISSE", result)

    def test_network_error_not_fabricated(self):
        def offline(_req, timeout):
            raise OSError("offline")
        result = retrieve_web_research("Wer ist aktuell Bundeskanzler?", opener=offline)
        self.assertIn("NICHT VERFÜGBAR", result)


if __name__ == "__main__":
    unittest.main()
