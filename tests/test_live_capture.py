"""Tests for the opt-in local live collector."""
import json
import unittest
from agent.live_capture import capture, validate_url


class LiveCaptureTests(unittest.TestCase):
    def test_only_explicit_loopback(self):
        for url in ("https://example.com/agent", "http://192.168.1.2/api",
                    "http://user:password@localhost:8010/agent"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)
        self.assertEqual(validate_url("http://127.0.0.1:8010/agent"),
                         "http://127.0.0.1:8010/agent")

    def test_collect_preserves_raw_response_and_latency(self):
        calls = []
        def transport(req, timeout):
            calls.append((req.method, json.loads(req.data), timeout))
            return json.dumps({"answer": "Test", "sources": []}).encode()
        rows = capture(["Frage A", "Frage B"], "http://127.0.0.1:8010/agent",
                       transport=transport)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["response"]["answer"], "Test")
        self.assertEqual(rows[0]["review_status"], "pending")
        self.assertGreaterEqual(rows[0]["elapsed_ms"], 0)
        self.assertEqual(calls[0][1], {"message": "Frage A"})

    def test_invalid_questions_are_rejected(self):
        with self.assertRaises(ValueError):
            capture([], "http://localhost:8010/agent")
        with self.assertRaises(ValueError):
            capture([""] * 2, "http://localhost:8010/agent")


if __name__ == "__main__":
    unittest.main()
