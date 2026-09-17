import unittest
from unittest import mock

from fastapi.testclient import TestClient

from agent import app


class ChatActionsWebSearchTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(
            app.app,
            base_url="http://localhost",
        )

    def test_current_news_executes_direct_web_search_tool(self):
        calls = []

        def fake_web_search(request):
            calls.append(request.prompt)

            return {
                "query": request.prompt,
                "provider": "test",
                "count": 1,
                "results": [
                    {
                        "title": "Fresh test result",
                        "url": "https://example.invalid/fresh",
                        "snippet": "Current test result",
                        "published_date": "2026-09-17",
                    }
                ],
                "current_date": "2026-09-17",
                "current_time": "2026-09-17T23:30:00+02:00",
            }

        with mock.patch.dict(
            app.TOOLS,
            {"web_search": fake_web_search},
            clear=False,
        ):
            response = self.client.post(
                "/api/chat/actions",
                json={
                    "prompt": (
                        "alle wichtigen news von heute "
                        "bitte gut zusammengefasst"
                    ),
                    "conversation_context": [],
                },
            )

        self.assertEqual(response.status_code, 200)

        result = response.json()

        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool"], "web_search")
        self.assertEqual(result["status"], "completed")

        self.assertEqual(
            result["data"]["current_date"],
            "2026-09-17",
        )

        self.assertEqual(len(result["data"]["results"]), 1)

        self.assertEqual(
            calls,
            [
                "alle wichtigen news von heute "
                "bitte gut zusammengefasst"
            ],
        )

    def test_current_news_does_not_become_research_agent(self):
        routing = app.classify_chat_action_details(
            "alle wichtigen news von heute bitte gut zusammengefasst",
            None,
            [],
        )

        self.assertEqual(
            routing["intent"],
            "web_search",
        )


if __name__ == "__main__":
    unittest.main()
