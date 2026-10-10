"""Offline tests for repeated benchmark aggregation."""
import unittest
from agent.repeated_benchmark import summarize_runs


class RepeatedBenchmarkTests(unittest.TestCase):
    def test_latency_median_and_flags(self):
        records = [
            {"id": "a", "question": "Q1", "elapsed_ms": 1000,
             "review_status": "pending",
             "response": {"answer": "Neu, seit 23.10.2099", "status": "completed",
                          "steps": [], "performance": {"events": []}}},
            {"id": "b", "question": "Q2", "elapsed_ms": 3000,
             "review_status": "pending",
             "response": {"answer": "391", "status": "completed", "steps": []}},
            {"id": "c", "question": "Q3", "elapsed_ms": 999,
             "review_status": "error", "error": "timeout"},
        ]
        result = summarize_runs(records)
        self.assertEqual(result["attempted"], 3)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["median_ms"], 2000)
        self.assertIn("future_date_inconsistency", result["cases"][0]["heuristic_flags"])

    def test_no_completed_runs(self):
        result = summarize_runs([{"id": "a", "question": "Q", "review_status": "error"}])
        self.assertIsNone(result["median_ms"])
        self.assertEqual(result["errors"], 1)


if __name__ == "__main__":
    unittest.main()
