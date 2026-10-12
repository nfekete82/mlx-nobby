"""Benchmark truth labels, shape, determinism and integration."""
import unittest
from agent.evidence_benchmark import cases, evaluate


class EvidenceBenchmarkTests(unittest.TestCase):
    def test_sixty_unique_balanced_cases(self):
        rows = cases()
        self.assertEqual(len(rows), 60)
        self.assertEqual(len({row["id"] for row in rows}), 60)
        self.assertEqual(sum(row["should_flag"] for row in rows), 30)

    def test_confusion_matrix_accounts_for_every_case(self):
        result = evaluate()
        counts = result["confusion_matrix"]
        self.assertEqual(sum(counts.values()), 60)
        self.assertEqual(result["cases"], 60)
        self.assertEqual(len(result["details"]), 60)

    def test_positive_and_negative_controls(self):
        result = evaluate()
        by_id = {row["id"]: row for row in result["details"]}
        self.assertTrue(by_id["supported-00"]["flagged"] is False)
        self.assertTrue(by_id["unsupported-00"]["flagged"])
        self.assertFalse(by_id["no_fetch-00"]["flagged"])
        self.assertFalse(by_id["undated_prediction-00"]["flagged"])

    def test_warning_state_matches_output(self):
        for case in evaluate()["details"]:
            self.assertEqual(case["flagged"], case["warning_in_output"])

    def test_metrics_are_bounded(self):
        result = evaluate()
        for name in ("precision", "recall", "false_positive_rate", "false_negative_rate"):
            if result[name] is not None:
                self.assertGreaterEqual(result[name], 0)
                self.assertLessEqual(result[name], 1)


if __name__ == "__main__":
    unittest.main()
