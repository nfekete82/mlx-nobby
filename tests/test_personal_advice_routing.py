"""Personal situations must be answerable without public web search."""
import unittest
from unittest import mock
from fastapi.testclient import TestClient

from agent import app as agent_app
from agent.personal_advice_routing import is_personal_advice_without_external_request


# Regression: the exact factual structure of the reported misrouting.
CHEF_CASE = (
    "mein chef ist so ein riesen vollidiot wir haben o2 angebote auf "
    "unserer webseite, lt. statistiken gehen die besucher drauf aber "
    "gehen relativ schnell wieder und die meisten geben feedback "
    "dass es einfach zu teuer ist. so alle statistiken sagen also das aus. "
    "jetzt sagt mein chef aber es liegt daran dass wir es nicht in "
    "jedem newsletter bewerben und er scheißt auf statistiken..."
)


class PersonalAdviceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(agent_app.app, base_url="http://localhost")

    def test_chef_story_is_regular_chat_without_a_web_tool(self):
        self.assertTrue(is_personal_advice_without_external_request(CHEF_CASE))
        self.assertEqual(agent_app._direct_chat_action(CHEF_CASE), "normal_chat")
        with mock.patch.object(
            agent_app, "semantic_intent_classifier",
            side_effect=AssertionError("Personal case must not use LLM classifier"),
        ), mock.patch.object(
            agent_app, "semantic_manager_classifier",
            side_effect=AssertionError("Personal case must not load manager classifier"),
        ):
            preflight = self.client.post("/api/chat/actions/route",
                                         json={"prompt": CHEF_CASE, "conversation_context": []})
            execution = self.client.post("/api/chat/actions",
                                         json={"prompt": CHEF_CASE, "conversation_context": []})
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["intent"], "normal_chat")
        self.assertEqual(execution.status_code, 200, execution.text)
        self.assertEqual(execution.json()["tool"], "normal_chat")
        self.assertEqual(execution.json()["status"], "not_applicable")

    def test_personal_stories_can_mention_prices_stats_sites_and_today(self):
        for prompt in (
            "Meine Chefin sagt heute, dass unsere Preise zu hoch sind. Wir haben Feedback, was soll ich tun?",
            "Mein Kollege behauptet, unsere Webseite wäre schuld. Wir haben aber andere Statistiken und ich bin genervt.",
            "Meine Mutter meint, ich sollte alles für sie tun. Ich finde den Streit sehr anstrengend.",
            "My boss says our website prices are perfect, but we get negative feedback and I disagree.",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(is_personal_advice_without_external_request(prompt))
                self.assertEqual(agent_app._direct_chat_action(prompt), "normal_chat")

    def test_explicit_public_questions_remain_web_eligible(self):
        for prompt in (
            "Mein Chef sagt, suche im Web nach den aktuellen O2 Angeboten.",
            "Meine Chefin sagt, was steht aktuell auf der O2 Webseite?",
            "Mein Chef sagt, recherchiere die neuesten Nachrichten heute.",
            "Mein Chef möchte, dass ich nach aktuellen Preisen suche.",
            "Mein Kollege sagt, google die aktuellen News heute.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(is_personal_advice_without_external_request(prompt))

    def test_plain_news_not_captured(self):
        result = agent_app.classify_chat_action_details("Was sind die aktuellen Nachrichten aus Deutschland?")
        self.assertEqual(result["intent"], "web_search")

    def test_legacy_misroute_empty_search_can_continue_without_web_facts(self):
        def empty_search(request):
            return {
                "provider": "SearXNG", "provider_status": "empty",
                "count": 0, "query": request.prompt, "results": [],
            }
        fake_route = {"intent": "web_search", "confidence": 1.0,
                      "requires_tools": True, "method": "mock_legacy_misroute"}
        with mock.patch.object(agent_app, "_chat_decision_for_request", return_value=None), \
             mock.patch.object(agent_app, "_requires_public_source_research", return_value=False), \
             mock.patch.object(agent_app, "_trusted_workspace_chat_action", return_value=None), \
             mock.patch.object(agent_app, "classify_chat_action_details",
                               return_value=fake_route), \
             mock.patch.dict(agent_app.TOOLS, {"web_search": empty_search}):
            response = self.client.post("/api/chat/actions",
                                        json={"prompt": CHEF_CASE, "conversation_context": []})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["tool"], "web_search")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["data"]["empty_search_chat_fallback"])
        self.assertEqual(result["data"]["results"], [])

    def test_empty_genuine_public_search_never_gets_chat_fallback(self):
        def empty_search(request):
            return {"provider": "SearXNG", "count": 0, "results": []}
        fake_route = {"intent": "web_search", "confidence": 1.0,
                      "requires_tools": True, "method": "mock_legacy_misroute"}
        with mock.patch.object(agent_app, "_chat_decision_for_request", return_value=None), \
             mock.patch.object(agent_app, "_requires_public_source_research", return_value=False), \
             mock.patch.object(agent_app, "_trusted_workspace_chat_action", return_value=None), \
             mock.patch.object(agent_app, "classify_chat_action_details",
                               return_value=fake_route), \
             mock.patch.dict(agent_app.TOOLS, {"web_search": empty_search}):
            response = self.client.post("/api/chat/actions", json={
                "prompt": "Mein Chef sagt, suche im Web nach aktuellen O2-Angeboten.",
                "conversation_context": [],
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("empty_search_chat_fallback", response.json()["data"])


if __name__ == "__main__":
    unittest.main()
