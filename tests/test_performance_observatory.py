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


    def test_buffered_vision_and_router_calls_do_not_create_fake_chat_speed(self):
        for index, purpose in enumerate(("router.classify", "chat.vision")):
            call = observability.ModelCallMetrics(
                trace_id=f"nonstream-{index:08d}",
                purpose=purpose,
                model="local-model",
                messages=[],
            )
            call.set_upstream_connect(10000.0)
            call.finish(
                usage={"prompt_tokens": 500, "completion_tokens": 100},
                output_text="buffered response",
            )

        snapshot = performance.model_performance_snapshot(limit=10)
        self.assertEqual(snapshot["summary"]["ttft_ms"]["count"], 0)
        self.assertEqual(snapshot["summary"]["tokens_per_second"]["count"], 0)
        self.assertEqual(snapshot["summary"]["total_ms"]["count"], 0)
        self.assertEqual(len(snapshot["recent_calls"]), 2)
        for call in snapshot["recent_calls"]:
            self.assertIsNone(call["timings_ms"]["ttft"])
            self.assertIsNone(call["tokens_per_second"])
            self.assertIsNotNone(call["timings_ms"]["total"])

    def test_router_stats_do_not_pollute_genuine_streaming_chat(self):
        router = observability.ModelCallMetrics(
            trace_id="router-activity-001", purpose="router.classify",
            messages=[],
        )
        router.set_upstream_connect(3000.0)
        router.finish(usage={"completion_tokens": 300})

        chat = observability.ModelCallMetrics(
            trace_id="real-chat-stream-001", purpose="chat.stream",
            messages=[],
        )
        chat.finish(usage={"prompt_tokens": 100, "completion_tokens": 40})
        with observability._TRACE_LOCK:
            chat.metric["timings_ms"].update({
                "ttft": 200.0,
                "generation": 1000.0,
                "total": 1200.0,
            })
        snapshot = performance.model_performance_snapshot(limit=10)
        self.assertEqual(snapshot["summary"]["ttft_ms"]["count"], 1)
        self.assertEqual(snapshot["summary"]["ttft_ms"]["p50"], 200.0)
        self.assertEqual(snapshot["summary"]["tokens_per_second"]["p50"], 40.0)

    def test_stream_without_first_token_does_not_invent_generation(self):
        chat = observability.ModelCallMetrics(
            trace_id="stream-no-token-001",
            purpose="chat.stream", messages=[],
        )
        chat.set_upstream_connect(1200.0)
        chat.finish(usage={"completion_tokens": 60})
        snapshot = performance.model_performance_snapshot(limit=10)
        self.assertEqual(snapshot["summary"]["ttft_ms"]["count"], 0)
        self.assertEqual(snapshot["summary"]["tokens_per_second"]["count"], 0)
        self.assertIsNone(snapshot["recent_calls"][0]["tokens_per_second"])


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
                    "provider_timing": {
                        "process_spawn_ms": 12.3,
                        "process_wall_ms": 3450,
                        "first_output_ms": float("inf"),
                        "tqdm_first_ms": 8100.0,
                        "tqdm_first_step": 0,
                        "tqdm_complete_ms": 58400.0,
                        "tqdm_window_ms": 50300.0,
                        "debug_prompt": "another secret",
                        "fresh_process": True,
                        "provider": "mflux",
                        "low_ram": True,
                        "mflux_cache_limit_gb": 4.0,
                        "steps": 20, "width": 1024, "height": 768,
                        "guidance": 1.0, "reference_count": 2,
                        "use_step_cache": False, "use_kv_cache": True,
                        "model_weights_path": "/private/model.safetensors",
                        "prompt": "do-not-expose-secret",
                    },
                    "performance_timings": {
                        "execution_ms": 4890,
                        "resource_wait_ms": 110,
                        "render_setup_ms": 100, "provider_and_setup_ms": 4000,
                        "output_finalize_ms": 150, "sdxl_unload_ms": 400,
                        "runtime_return_ms": 240, "private_text": "hidden",
                        "negative": -5,
                        "source_path": "/private/image.png",
                    },
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
        self.assertEqual(image["provider_timing"]["process_spawn_ms"], 12.3)
        self.assertEqual(image["provider_timing"]["process_wall_ms"], 3450)
        self.assertIsNone(image["provider_timing"]["first_output_ms"])
        self.assertEqual(image["provider_timing"]["tqdm_first_ms"], 8100.0)
        self.assertEqual(image["provider_timing"]["tqdm_first_step"], 0)
        self.assertEqual(image["provider_timing"]["tqdm_complete_ms"], 58400.0)
        self.assertEqual(image["provider_timing"]["tqdm_window_ms"], 50300.0)
        self.assertNotIn("another secret", json.dumps(snapshot))
        self.assertIs(image["provider_timing"]["fresh_process"], True)
        self.assertEqual(image["provider_timing"]["provider"], "mflux")
        self.assertIs(image["provider_timing"]["low_ram"], True)
        self.assertEqual(image["provider_timing"]["mflux_cache_limit_gb"], 4.0)
        self.assertEqual(image["provider_timing"]["steps"], 20)
        self.assertEqual(image["provider_timing"]["width"], 1024)
        self.assertEqual(image["provider_timing"]["height"], 768)
        self.assertEqual(image["provider_timing"]["reference_count"], 2)
        self.assertEqual(image["provider_timing"]["guidance"], 1.0)
        self.assertIs(image["provider_timing"]["use_step_cache"], False)
        self.assertIs(image["provider_timing"]["use_kv_cache"], True)
        self.assertNotIn("/private/model.safetensors", json.dumps(snapshot))
        self.assertEqual(image["performance_timings"]["execution_ms"], 4890)
        self.assertEqual(image["performance_timings"]["sdxl_unload_ms"], 400)
        self.assertEqual(image["performance_timings"]["runtime_return_ms"], 240)
        self.assertNotIn("hidden", json.dumps(snapshot))
        self.assertEqual(image["performance_timings"]["resource_wait_ms"], 110)
        self.assertNotIn("do-not-expose-secret", json.dumps(snapshot))
        self.assertNotIn("/private/image.png", json.dumps(snapshot))
        self.assertNotIn("source_path", json.dumps(snapshot))
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
                        "version": 2,
                        "duration_ms": 125.567,
                        "chat_released": True,
                        "image_released": False,
                        "image_preserved": True,
                        "speech_released": True,
                        "timings_ms": {
                            "lease_wait": 21.123,
                            "image_release": 40.0,
                            "speech_release": 60.0,
                            "musetalk_release": -4,
                            "chat_stop": float("inf"),
                            "private_key": "secret-prompt",
                        },
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
                        "image_released": True,
                        "image_preserved": True,
                        "timings_ms": {
                            "lease_wait": float("nan"),
                            "image_release": "500",
                        },
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
        self.assertFalse(jobs["a" * 24]["image_released"])
        self.assertTrue(jobs["a" * 24]["image_preserved"])
        self.assertEqual(jobs["a" * 24]["handoff_stages_ms"]["lease_wait"], 21.12)
        self.assertIsNone(jobs["a" * 24]["handoff_stages_ms"]["musetalk_release"])
        self.assertIsNone(jobs["a" * 24]["handoff_stages_ms"]["chat_stop"])
        self.assertIsNone(jobs["b" * 24]["image_released"])
        self.assertIsNone(jobs["b" * 24]["image_preserved"])
        self.assertIsNone(jobs["b" * 24]["handoff_ms"])
        self.assertIsNone(jobs["b" * 24]["chat_released"])
        self.assertIsNone(jobs["c" * 24]["handoff_ms"])
        self.assertEqual(snapshot["summary"]["video"]["handoff_ms"]["count"], 1)
        self.assertEqual(snapshot["summary"]["video"]["chat_releases"], 1)
        self.assertEqual(snapshot["summary"]["video"]["image_releases"], 0)
        self.assertEqual(snapshot["summary"]["video"]["image_release_samples"], 1)
        self.assertEqual(snapshot["summary"]["video"]["image_preserves"], 1)
        self.assertEqual(snapshot["summary"]["video"]["image_preserve_samples"], 1)
        stage_summary = snapshot["summary"]["video"]["handoff_stages_ms"]
        self.assertEqual(stage_summary["lease_wait"]["p50"], 21.12)
        self.assertEqual(stage_summary["image_release"]["p50"], 40)
        self.assertEqual(stage_summary["chat_stop"]["count"], 0)
        serialized = json.dumps(snapshot)
        self.assertNotIn("NaN", serialized)
        self.assertNotIn("Infinity", serialized)
        self.assertNotIn("secret-prompt", serialized)
        self.assertNotIn("private_key", serialized)


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
