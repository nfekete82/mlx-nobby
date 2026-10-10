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

    def test_p95_failure_rate_timings_tokens_and_privacy(self):
        records = [{"id": str(i), "question": "private prompt", "question_index": 1,
                    "elapsed_ms": i * 100, "captured_at": "2026-10-11T12:00:00+00:00",
                    "review_status": "pending", "response": {"answer": "391",
                    "performance": {"events": [{"action": "provider.complete",
                    "lease_wait_ms": 20, "lock_wait_ms": 1, "total_tokens": 12,
                    "prompt_tokens": 10, "completion_tokens": 2,
                    "observed_holder_role": "secret prompt"}]}}} for i in range(1, 6)]
        records.append({"id": "error", "question": "private prompt", "review_status": "error"})
        result = summarize_runs(records)
        self.assertEqual(result["median_ms"], 300)
        self.assertEqual(result["p95_ms"], 500)
        self.assertEqual(result["error_rate"], 1 / 6)
        self.assertEqual(result["cases"][0]["timings_ms"]["lease_wait_ms"], 20)
        self.assertEqual(result["cases"][0]["known_total_tokens"], 12)
        self.assertNotIn("private prompt", str(result))
        self.assertNotIn("secret prompt", str(result))


if __name__ == "__main__":
    unittest.main()
