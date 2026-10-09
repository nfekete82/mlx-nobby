"""Offline tests for the opt-in chat latency probe."""
import argparse
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark-chat-latency.py"
spec = importlib.util.spec_from_file_location("benchmark_chat_latency", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BenchmarkChatLatencyTests(unittest.TestCase):
    def test_loopback_rejects_remote_and_credentials(self):
        for url in ("https://127.0.0.1:8000", "http://example.com",
                    "http://user:pass@localhost:8000", "http://localhost:8000/api",
                    "http://localhost:8000?x=1"):
            with self.subTest(url=url), self.assertRaises(argparse.ArgumentTypeError):
                module.validate_loopback(url)
        self.assertEqual(module.validate_loopback("http://127.0.0.1:8000/"),
                         "http://127.0.0.1:8000")

    def test_bounds_and_finite_metrics(self):
        self.assertEqual(module.positive_int("20"), 20)
        with self.assertRaises(argparse.ArgumentTypeError):
            module.positive_int("21")
        self.assertEqual(module.bounded_int("90", 1, 600), 90)
        with self.assertRaises(argparse.ArgumentTypeError):
            module.bounded_int("601", 1, 600)
        for value in (None, "1", float("nan"), float("inf"), -1, True):
            self.assertIsNone(module.finite_ms(value))

    def test_percentiles_exclude_missing_data(self):
        self.assertEqual(module.summarize([None]), {"count": 0, "p50_ms": None, "p95_ms": None})
        self.assertEqual(module.summarize([0, 10, None, 20])["p50_ms"], 10)
        self.assertEqual(module.summarize([0, 10, None, 20])["p95_ms"], 19)

    def test_sample_records_only_metrics(self):
        fake = Mock()
        fake.json.return_value = {
            "choices": [{"message": {"content": "private completion"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 2},
            "timings": {"prompt_ms": 234, "predicted_ms": 51}
        }
        client = Mock()
        client.post.return_value = fake
        with patch.object(module.time, "monotonic", side_effect=[1., 1.5]):
            result = module.sample(client, "loaded-model", 90)
        self.assertEqual(result["wall_ms"], 500)
        self.assertEqual(result["prompt_ms"], 234)
        self.assertEqual(result["completion_tokens"], 2)
        self.assertNotIn("private completion", str(result))
        self.assertEqual(client.post.call_args.kwargs["timeout"], 90)
        self.assertFalse(client.post.call_args.kwargs["json"]["stream"])


if __name__ == "__main__":
    unittest.main()
