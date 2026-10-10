"""Deterministic timing aggregation checks."""
import unittest
from agent.performance_summary import summarize_performance


class PerformanceSummaryTests(unittest.TestCase):
    def test_missing_profile(self):
        self.assertFalse(summarize_performance({"answer": "ok"})["available"])

    def test_sums_calls_without_sensitive_payload(self):
        response = {"performance": {"events": [
            {"phase": "tool", "action": "fetch_url", "duration_ms": 120.5},
            {"phase": "tool", "action": "fetch_url", "duration_ms": 79.5},
            {"phase": "model", "action": "provider.complete", "duration_ms": 510},
            {"phase": "tool", "action": "fetch_url", "duration_ms": -1},
        ]}}
        data = summarize_performance(response)
        self.assertEqual(data["events"], 3)
        self.assertEqual(data["by_action_ms"]["tool:fetch_url"]["total"], 200)
        self.assertEqual(data["by_action_ms"]["tool:fetch_url"]["calls"], 2)
        self.assertNotIn("answer", data)


if __name__ == "__main__":
    unittest.main()
