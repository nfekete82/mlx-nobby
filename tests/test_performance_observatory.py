import json
import unittest
from unittest import mock

from fastapi import FastAPI

from agent import performance_observatory_routes as performance
from backend import observability
from backend import performance_observatory_routes as web_performance


class PerformanceSeriesTests(unittest.TestCase):
    def test_metric_series_reports_average_and_percentiles(self):
        series = performance.metric_series([10, 20, 30, 40])

        self.assertEqual(series["count"], 4)
        self.assertEqual(series["latest"], 40.0)
        self.assertEqual(series["average"], 25.0)
        self.assertEqual(series["p50"], 25.0)
        self.assertEqual(series["p95"], 38.5)
        self.assertEqual(series["min"], 10.0)
        self.assertEqual(series["max"], 40.0)

    def test_empty_metric_series_is_explicit(self):
        series = performance.metric_series([None, float("nan")])
        self.assertEqual(series["count"], 0)
        self.assertIsNone(series["p50"])
        self.assertIsNone(series["average"])


class ModelPerformanceTests(unittest.TestCase):
    def setUp(self):
        observability.reset_metrics()

    def tearDown(self):
        observability.reset_metrics()

    def test_chat_snapshot_computes_tokens_per_second_without_content(self):
        secret = "do-not-retain-this-performance-prompt"
        call = observability.ModelCallMetrics(
            trace_id="performance-trace-001",
            purpose="chat.stream",
            model="/Users/example/Models/chat-model",
            role="chat",
            backend="mlx_lm",
            messages=[{"role": "user", "content": secret}],
        )
        call.finish(
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
            output_text="also-private",
        )
        with observability._TRACE_LOCK:
            call.metric["timings_ms"].update({
                "ttft": 250.0,
                "generation": 1000.0,
                "total": 1250.0,
            })

        snapshot = performance.model_performance_snapshot(limit=10)
        recent = snapshot["recent_calls"][0]

        self.assertEqual(recent["model"]["identifier"], "chat-model")
        self.assertEqual(recent["tokens_per_second"], 20.0)
        self.assertEqual(snapshot["summary"]["ttft_ms"]["p50"], 250.0)
        self.assertEqual(
            snapshot["summary"]["tokens_per_second"]["p50"],
            20.0,
        )
        serialized = json.dumps(snapshot)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("also-private", serialized)
        self.assertNotIn("/Users/example", serialized)


class MediaPerformanceTests(unittest.TestCase):
    def test_media_snapshot_calculates_queue_generation_and_total_time(self):
        queue_snapshot = {
            "active_count": 1,
            "waiting_count": 2,
            "jobs": [
                {
                    "id": "a" * 24,
                    "kind": "image",
                    "status": "completed",
                    "phase": "completed",
                    "model": "/Users/example/Models/image-model",
                    "created_at": 100.0,
                    "started_at": 102.0,
                    "finished_at": 107.0,
                    "title": "private image prompt",
                },
                {
                    "id": "b" * 24,
                    "kind": "video",
                    "status": "completed",
                    "model": "ltx-video",
                    "created_at": 200.0,
                    "started_at": 203.0,
                    "finished_at": 215.0,
                },
            ],
        }

        snapshot = performance.media_performance_snapshot(queue_snapshot, limit=10)
        image = next(
            job for job in snapshot["recent_jobs"] if job["kind"] == "image"
        )

        self.assertEqual(image["model"], "image-model")
        self.assertEqual(image["queue_wait_ms"], 2000.0)
        self.assertEqual(image["generation_ms"], 5000.0)
        self.assertEqual(image["total_ms"], 7000.0)
        self.assertEqual(
            snapshot["summary"]["video"]["generation_ms"]["average"],
            12000.0,
        )
        self.assertNotIn("private image prompt", json.dumps(snapshot))


    def test_video_handoff_metrics_are_sanitized_and_summarized(self):
        queue_snapshot = {
            "active_count": 0,
            "waiting_count": 0,
            "jobs": [
                {
                    "id": "a" * 24,
                    "kind": "video",
                    "status": "completed",
                    "created_at": 1.0,
                    "started_at": 2.0,
                    "finished_at": 10.0,
                    "runtime_handoff": {
                        "duration_ms": 125.567,
                        "chat_released": True,
                        "speech_released": True,
                    },
                },
                {
                    "id": "b" * 24,
                    "kind": "video",
                    "status": "completed",
                    "created_at": 11.0,
                    "started_at": 12.0,
                    "finished_at": 20.0,
                    "runtime_handoff": {
                        "duration_ms": float("nan"),
                        "chat_released": "true",
                    },
                },
                {
                    "id": "c" * 24,
                    "kind": "image",
                    "status": "completed",
                    "runtime_handoff": {"duration_ms": -12},
                },
            ],
        }

        snapshot = performance.media_performance_snapshot(queue_snapshot)
        jobs = {job["id"]: job for job in snapshot["recent_jobs"]}
        self.assertEqual(jobs["a" * 24]["handoff_ms"], 125.57)
        self.assertTrue(jobs["a" * 24]["chat_released"])
        self.assertIsNone(jobs["b" * 24]["handoff_ms"])
        self.assertIsNone(jobs["b" * 24]["chat_released"])
        self.assertIsNone(jobs["c" * 24]["handoff_ms"])
        self.assertEqual(snapshot["summary"]["video"]["handoff_ms"]["count"], 1)
        self.assertEqual(snapshot["summary"]["video"]["chat_releases"], 1)
        self.assertNotIn("NaN", json.dumps(snapshot))


class PerformanceSnapshotTests(unittest.TestCase):
    def test_snapshot_combines_memory_runtime_model_and_media_metrics(self):
        queue_snapshot = {
            "jobs": [],
            "active_count": 0,
            "waiting_count": 0,
            "runtime": {"active": None, "waiting": [], "waiting_count": 0},
        }
        memory = {
            "total_gb": 48.0,
            "headroom_gb": 18.0,
            "swap_used_gb": 1.5,
            "pressure": "normal",
        }
        runtimes = {
            "chat": {"available": True, "loaded": True, "state": "warm"},
            "image": {"available": True, "loaded": False, "state": "cold"},
            "video": {"available": False, "loaded": False, "state": "unavailable"},
        }

        with mock.patch.object(
            performance.media_queue,
            "snapshot",
            return_value=queue_snapshot,
        ), mock.patch.object(
            performance.runtime_coordinator,
            "memory_budget_snapshot",
            return_value=memory,
        ), mock.patch.object(
            performance,
            "runtime_snapshot",
            return_value=runtimes,
        ):
            snapshot = performance.build_performance_snapshot(limit=10)

        self.assertEqual(snapshot["version"], 2)
        self.assertEqual(snapshot["system"]["memory"]["headroom_gb"], 18.0)
        self.assertEqual(snapshot["system"]["runtimes"]["chat"]["state"], "warm")
        self.assertEqual(snapshot["system"]["runtimes"]["image"]["state"], "cold")
        self.assertIn("in-memory", snapshot["notes"]["model_history"])

    def test_observatory_reuses_queue_memory_without_second_probe(self):
        memory = {"total_gb": 48.0, "headroom_gb": 13.5,
                  "pressure": "normal"}
        queue_snapshot = {
            "jobs": [], "active_count": 0, "waiting_count": 0,
            "runtime": {
                "active": None, "waiting": [], "waiting_count": 0,
                "memory": memory,
            },
        }
        with mock.patch.object(
            performance.media_queue, "snapshot", return_value=queue_snapshot
        ), mock.patch.object(
            performance.runtime_coordinator, "memory_budget_snapshot"
        ) as os_probe, mock.patch.object(
            performance, "runtime_snapshot", return_value={}
        ):
            result = performance.build_performance_snapshot(limit=10)

        self.assertEqual(result["system"]["memory"], memory)
        self.assertEqual(result["system"]["runtime_lease"]["memory"], memory)
        os_probe.assert_not_called()

    def test_agent_route_is_installed_once(self):
        app = FastAPI()
        performance.install_routes(app, status_provider=lambda: {"online": True})
        performance.install_routes(app, status_provider=lambda: {"online": True})

        paths = [getattr(route, "path", None) for route in app.router.routes]
        self.assertEqual(paths.count("/api/performance/observatory"), 1)


class PerformanceWebTests(unittest.TestCase):
    def test_assets_are_injected_once(self):
        html = (
            b"<html><body>"
            + web_performance.CHAT_SCRIPT_MARKER
            + b"</body></html>"
        )
        once = web_performance.inject_performance_observatory_assets(html)
        twice = web_performance.inject_performance_observatory_assets(once)

        self.assertIn(web_performance.PERFORMANCE_OBSERVATORY_ASSETS, once)
        self.assertEqual(once, twice)

    def test_proxy_route_clamps_limit(self):
        calls = []

        def request(method, path, payload=None, timeout=0):
            calls.append((method, path, payload, timeout))
            return {"ok": True}

        app = FastAPI()
        web_performance.install_routes(app, request)
        route = next(
            item for item in app.router.routes
            if getattr(item, "path", None) == "/api/mlx/performance/observatory"
        )
        result = route.endpoint(limit=500)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("limit=100", calls[0][1])
        self.assertEqual(calls[0][3], 20)


if __name__ == "__main__":
    unittest.main()
