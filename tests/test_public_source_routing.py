"""Public source-required questions should not silently fall back to memory."""
import unittest

from agent.app import _requires_public_source_research, _public_sources_route


class PublicSourceRoutingTests(unittest.TestCase):
    def test_dated_public_question_with_sources_requires_research(self):
        prompt = "Welche Elektroautos wurden 2026 vorgestellt? Nenne die zehn wichtigsten Modelle mit konkreten Quellen."
        self.assertTrue(_requires_public_source_research(prompt))
        route = _public_sources_route()
        self.assertEqual(route["intent"], "research_agent")
        self.assertTrue(route["requires_tools"])

    def test_article_link_wording_starts_research(self):
        prompt = ("Welche Elektroautos wurden 2026 tatsächlich vorgestellt? "
                  "Nenne nur nachweislich belegte Modelle und verlinke für jedes Modell den konkreten Artikel.")
        self.assertTrue(_requires_public_source_research(prompt))

    def test_recent_phone_launches_require_research_without_explicit_links(self):
        prompt = "welche handys wurden in den letzten 3 monaten vorgestellt?"
        self.assertTrue(_requires_public_source_research(prompt))

    def test_no_public_research_for_private_prompts(self):
        self.assertFalse(_requires_public_source_research("Welche Quellen gibt es 2026 für mein Portfolio?"))
        self.assertFalse(_requires_public_source_research("Was ist neu in meinem Workspace 2026? Nenne Quellen."))


if __name__ == "__main__":
    unittest.main()
