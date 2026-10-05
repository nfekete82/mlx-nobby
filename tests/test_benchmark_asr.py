import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-asr.py"
SPEC = importlib.util.spec_from_file_location("benchmark_asr", SCRIPT)
benchmark_asr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark_asr)


class BenchmarkAsrTests(unittest.TestCase):
    def test_word_error_rate_normalizes_case_and_punctuation(self):
        self.assertEqual(
            benchmark_asr.word_error_rate(
                "Hallo, Nobby! Wie geht es dir?",
                "hallo nobby wie geht es dir",
            ),
            0.0,
        )
        self.assertAlmostEqual(
            benchmark_asr.word_error_rate("eins zwei drei", "eins vier drei"),
            1 / 3,
        )
        self.assertIsNone(benchmark_asr.word_error_rate("", "anything"))

    def test_sidecar_reference_uses_same_stem_txt(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.wav"
            audio.write_bytes(b"RIFF")
            self.assertIsNone(benchmark_asr.sidecar_reference(audio))
            audio.with_suffix(".txt").write_text("  Referenztext  \n", encoding="utf-8")
            self.assertEqual(benchmark_asr.sidecar_reference(audio), "Referenztext")

    def test_summary_combines_timing_and_reference_accuracy(self):
        payload = {
            "model": "candidate",
            "load_seconds": 2.0,
            "runs": [
                {"audio": "/tmp/a.wav", "seconds": 1.0, "text": "eins zwei drei"},
                {"audio": "/tmp/a.wav", "seconds": 3.0, "text": "eins zwei vier"},
            ],
        }
        summary = benchmark_asr.summarize_model(
            payload,
            {"/tmp/a.wav": "eins zwei drei"},
        )
        self.assertEqual(summary["median_seconds"], 2.0)
        self.assertAlmostEqual(summary["median_wer"], 1 / 6)
        self.assertEqual(summary["transcriptions"], 2)

    def test_recommendation_prefers_accuracy_before_speed(self):
        summaries = [
            {"model": "fast", "median_seconds": 0.2, "median_wer": 0.25},
            {"model": "accurate", "median_seconds": 1.0, "median_wer": 0.05},
        ]
        result = benchmark_asr.recommendation(summaries)
        self.assertEqual(result["winner"], "accurate")
        self.assertIn("WER", result["reason"])

    def test_recommendation_uses_speed_without_references(self):
        summaries = [
            {"model": "slow", "median_seconds": 2.0, "median_wer": None},
            {"model": "fast", "median_seconds": 0.5, "median_wer": None},
        ]
        result = benchmark_asr.recommendation(summaries)
        self.assertEqual(result["winner"], "fast")
        self.assertIn("sidecars", result["reason"])

    def test_asr_decision_records_winner_and_rejected_alternative(self):
        summaries = [
            {
                "model": "whisper",
                "load_seconds": 18.4,
                "transcriptions": 3,
                "median_seconds": 0.67,
                "mean_seconds": 2.53,
                "median_wer": 0.0,
                "mean_wer": 0.0,
            },
            {
                "model": "qwen-asr",
                "load_seconds": 1.8,
                "transcriptions": 3,
                "median_seconds": 0.99,
                "mean_seconds": 1.44,
                "median_wer": 0.0,
                "mean_wer": 0.0,
            },
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            benchmark_asr.model_evaluations,
            "EVALUATIONS_FILE",
            Path(directory) / "evaluations.json",
        ):
            evaluations = benchmark_asr.record_asr_evaluations(
                summaries,
                {
                    "winner": "whisper",
                    "reason": "lowest median WER, then lowest median inference time",
                },
            )
            latest = benchmark_asr.model_evaluations.list_latest()

        self.assertEqual(len(evaluations), 2)
        by_model = {item["model"]: item for item in latest}
        self.assertEqual(by_model["whisper"]["status"], "keep")
        self.assertEqual(by_model["qwen-asr"]["status"], "rejected")
        self.assertEqual(by_model["qwen-asr"]["compared_to"], "whisper")
        self.assertEqual(by_model["qwen-asr"]["metrics"]["median_seconds"], 0.99)


if __name__ == "__main__":
    unittest.main()
