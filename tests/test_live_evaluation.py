"""Validation and scoring tests for manually reviewed live data."""
import json
import tempfile
import unittest
from pathlib import Path
from agent.live_evaluation import load_records, summarize


def row(label_before="incorrect", label_after="correct", ident="case-1"):
    return {
        "id": ident, "question": "What does the official product page say?",
        "reference_urls": ["https://example.org/product"],
        "before": {"answer": "Unconfirmed claim.", "elapsed_ms": 110},
        "after": {"answer": "Corrected claim.", "elapsed_ms": 140},
        "review": {"reviewer": "human-01", "before": label_before,
                   "after": label_after}
    }


class LiveEvaluationTests(unittest.TestCase):
    def test_manual_review_scores_and_latency(self):
        result = summarize([row(), row("correct", "incorrect", "case-2")])
        self.assertEqual(result["cases"], 2)
        self.assertEqual(result["incorrect_to_correct"], 1)
        self.assertEqual(result["correct_to_noncorrect"], 1)
        self.assertEqual(result["mean_added_ms"], 30)
        self.assertEqual(result["correct_rate_after"], 0.5)

    def test_no_unreviewed_records_accepted(self):
        sample = row()
        sample["review"].pop("reviewer")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jsonl"
            path.write_text(json.dumps(sample), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path)

    def test_duplicate_identifiers_rejected(self):
        sample = json.dumps(row())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jsonl"
            path.write_text(sample + "\n" + sample, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path)

    def test_roundtrip_valid_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jsonl"
            path.write_text(json.dumps(row()) + "\n", encoding="utf-8")
            self.assertEqual(len(load_records(path)), 1)


if __name__ == "__main__":
    unittest.main()
