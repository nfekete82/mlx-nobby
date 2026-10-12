"""Verify token efficiency summarization without prompt disclosure."""
import unittest
from agent.model_efficiency import model_efficiency


class ModelEfficiencyTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(model_efficiency({})["call_count"], 0)

    def test_usage_and_no_prompt_leak(self):
        response = {"performance": {"events": [
            {"phase": "model", "action": "provider.complete",
             "duration_ms": 1200, "input_chars": 9000,
             "prompt_tokens": 2100, "completion_tokens": 200,
             "effective_output_tokens_per_s": 166.67,
             "private_prompt": "secret"},
            {"phase": "tool", "action": "fetch_url", "duration_ms": 100},
            {"phase": "model", "action": "provider.complete",
             "duration_ms": 2000},
        ]}}
        summary = model_efficiency(response)
        self.assertEqual(summary["call_count"], 2)
        self.assertEqual(summary["known_prompt_tokens"], 2100)
        self.assertEqual(summary["known_completion_tokens"], 200)
        self.assertNotIn("private_prompt", str(summary))


if __name__ == "__main__":
    unittest.main()
