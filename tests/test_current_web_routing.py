import unittest
from unittest import mock

from agent import app as agent_app


class CurrentWebRoutingTests(unittest.TestCase):

    def test_today_news_stays_web_search_with_coding_context(self):
        conversation_context = [
            {
                "role": "assistant",
                "content": "coding_agent workspace patch"
            },
            {
                "role": "user",
                "content": "Bitte repariere das Frontend im aktiven Workspace."
            },
        ]

        with (
            mock.patch.object(
                agent_app,
                "_looks_like_cross_capability_request",
                return_value=True,
            ),
            mock.patch.object(
                agent_app,
                "semantic_intent_classifier",
                side_effect=AssertionError(
                    "current news must bypass semantic routing"
                ),
            ),
        ):
            result = agent_app.classify_chat_action_details(
                "bitte die wichtigsten news heute",
                conversation_context=conversation_context,
            )

        self.assertEqual(
            result["intent"],
            "web_search",
        )
        self.assertEqual(
            result["method"],
            "deterministic",
        )

    def test_current_german_news_routes_to_web(self):
        result = agent_app.classify_chat_action_details(
            "Was sind die aktuellen Nachrichten aus Deutschland?"
        )

        self.assertEqual(
            result["intent"],
            "web_search",
        )

    def test_today_personal_statement_does_not_force_web(self):
        result = agent_app._direct_chat_action(
            "Heute hatte ich einen schlechten Tag."
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
