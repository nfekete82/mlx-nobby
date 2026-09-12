import json
import time
import unittest
from unittest import mock

from backend import observability


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        observability.reset_metrics()

    def test_trace_is_stable_and_request_ids_are_unique(self):
        with observability.trace_context("trace-turn-001") as trace_id:
            first = observability.ModelCallMetrics(
                purpose="router.classify",
                messages=[{"role": "user", "content": "hello"}],
            )
            first.finish(output_text="route")
            second = observability.ModelCallMetrics(
                purpose="chat.stream",
                messages=[{"role": "user", "content": "hello"}],
            )
            second.mark_first_token()
            time.sleep(0.001)
            second.finish(output_text="answer", finish_reason="stop")

        snapshot = observability.trace_snapshot(trace_id)
        self.assertEqual(snapshot["trace_id"], "trace-turn-001")
        self.assertEqual(snapshot["model_calls_in_turn"], 2)
        self.assertEqual(
            {call["trace_id"] for call in snapshot["calls"]},
            {"trace-turn-001"},
        )
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual(
            snapshot["calls"][1]["parent_request_id"],
            first.request_id,
        )
        self.assertTrue(all(
            call["model_calls_in_turn"] == 2
            for call in snapshot["calls"]
        ))
        self.assertIsNotNone(
            snapshot["calls"][1]["timings_ms"]["ttft"]
        )
        self.assertIsNotNone(
            snapshot["calls"][1]["timings_ms"]["generation"]
        )

    def test_upstream_usage_is_preserved(self):
        call = observability.ModelCallMetrics(
            trace_id="trace-usage-001",
            purpose="chat.stream",
            messages=[],
        )
        call.finish(
            usage={
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "completion_tokens_details": {
                    "reasoning_tokens": 3,
                },
            },
            output_text="ignored for upstream usage",
        )

        self.assertEqual(call.metric["usage"], {
            "input_tokens": 11,
            "output_tokens": 7,
            "reasoning_tokens": 3,
            "total_tokens": 18,
            "count_method": "upstream",
        })

    def test_missing_usage_uses_explicit_estimate(self):
        call = observability.ModelCallMetrics(
            trace_id="trace-estimate-001",
            purpose="chat.runtime",
            messages=[{"role": "user", "content": "12345678"}],
        )
        call.finish(output_text="1234")

        self.assertEqual(call.metric["usage"]["count_method"], "estimate")
        self.assertGreater(call.metric["usage"]["input_tokens"], 0)
        self.assertEqual(call.metric["usage"]["output_tokens"], 1)

    def test_metrics_contain_counts_but_no_prompt_content(self):
        secret_text = "unique-private-prompt-value"
        sources = {
            source: {"characters": index + 1, "items": 1}
            for index, source in enumerate(observability.CONTEXT_SOURCES)
        }
        call = observability.ModelCallMetrics(
            trace_id="trace-private-001",
            purpose="agent.plan",
            model="/Users/example/private-model",
            messages=[{"role": "user", "content": secret_text}],
            context_sources=sources,
        )
        call.finish(output_text="private-output-value")

        serialized = json.dumps(
            observability.trace_snapshot("trace-private-001")
        )
        self.assertNotIn(secret_text, serialized)
        self.assertNotIn("private-output-value", serialized)
        self.assertNotIn("/Users/example", serialized)
        self.assertEqual(
            [entry["source"] for entry in call.metric["context"]],
            list(observability.CONTEXT_SOURCES),
        )
        self.assertEqual(
            call.metric["model"]["identifier"],
            "private-model",
        )

    def test_call_counter_remains_exact_when_details_are_bounded(self):
        with mock.patch.object(
            observability,
            "MAX_RETAINED_CALLS_PER_TRACE",
            2,
        ):
            for index in range(3):
                call = observability.ModelCallMetrics(
                    trace_id="trace-bounded-001",
                    purpose=f"call.{index}",
                    messages=[],
                )
                call.finish()

        snapshot = observability.trace_snapshot("trace-bounded-001")
        self.assertEqual(snapshot["model_calls_in_turn"], 3)
        self.assertEqual(snapshot["calls_retained"], 2)
        self.assertEqual(snapshot["calls_truncated"], 1)
        self.assertEqual(
            [call["model_call_index"] for call in snapshot["calls"]],
            [2, 3],
        )


if __name__ == "__main__":
    unittest.main()
