import threading
import unittest
from pathlib import Path
from unittest import mock

import video_providers_mlx as mlx


class FakeProcess:
    def poll(self):
        return None


class VideoMlxWarmRuntimeTests(unittest.TestCase):
    def tearDown(self):
        with mlx._RUNTIME_LOCK:
            if mlx._WARM_TIMER is not None:
                mlx._WARM_TIMER.cancel()
            mlx._WARM_TIMER = None
            mlx._WARM_RUNTIME = None

    def test_acquire_reuses_healthy_worker_for_same_model(self):
        runtime = mlx.MlxWarmRuntime(FakeProcess(), mock.Mock(closed=False), Path("/models/q4"))
        mlx._WARM_RUNTIME = runtime
        model = {"id": "ltx-2.5-mlx-q4", "provider": "ltx-mlx"}
        with mock.patch.object(mlx.video_registry, "model_path", return_value=Path("/models/q4")), \
             mock.patch.object(mlx, "_runtime_alive", return_value=True), \
             mock.patch.object(mlx, "_start_runtime") as start:
            selected, reused = mlx._acquire_runtime(model, threading.Event())
        self.assertIs(selected, runtime)
        self.assertTrue(reused)
        start.assert_not_called()

    def test_successful_worker_is_kept_for_idle_reuse(self):
        runtime = mlx.MlxWarmRuntime(FakeProcess(), mock.Mock(closed=False), Path("/models/q4"))
        mlx._WARM_RUNTIME = runtime
        with mock.patch.object(mlx, "_runtime_alive", return_value=True), \
             mock.patch.object(mlx, "_schedule_warm_shutdown_locked") as schedule:
            mlx.unload(runtime)
        schedule.assert_called_once_with()

    def test_warm_status_exposes_worker_reuse_counter_without_weights_claim(self):
        runtime = mlx.MlxWarmRuntime(FakeProcess(), mock.Mock(closed=False), Path("/models/q4"))
        mlx._WARM_RUNTIME = runtime
        with mock.patch.object(mlx, "_runtime_alive", return_value=True), \
             mock.patch.object(mlx, "_json_request", return_value={
                 "generation_count": 2,
                 "busy": False,
                 "weights_resident": False,
             }):
            status = mlx.warm_runtime_status()
        self.assertTrue(status["loaded"])
        self.assertEqual(status["backend"], "mlx-worker")
        self.assertEqual(status["requests_completed"], 2)
        self.assertFalse(status["weights_resident"])

    def test_worker_source_uses_low_memory_pipeline_and_parent_watchdog(self):
        source = Path("video_mlx_worker.py").read_text()
        self.assertIn("DistilledPipeline", source)
        self.assertIn("low_memory=True", source)
        self.assertIn("low_ram_streaming=LOW_RAM", source)
        self.assertIn('"weights_resident": False', source)
        self.assertIn("LTX_MLX_PARENT_PID", source)

    def test_worker_source_maps_upstream_step_hook_to_live_progress(self):
        source = Path("video_mlx_worker.py").read_text()
        self.assertIn("def _install_progress_hook", source)
        self.assertIn("pipe._stepwise_hook = stepwise_hook", source)
        self.assertIn('phase="denoising"', source)
        self.assertIn("0.9 * completed / total_steps", source)

    def test_benchmark_records_failures_instead_of_aborting_first_backend(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertIn("def failed_result", source)
        self.assertIn("results.append(failed_result(model, exc))", source)
        self.assertIn("Kein Benchmark-Backend konnte einen Lauf abschließen", source)

    def test_benchmark_prints_periodic_heartbeat(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertIn("HEARTBEAT_SECONDS", source)
        self.assertIn("heartbeat_due", source)
        self.assertIn("elapsed_text", source)


if __name__ == "__main__":
    unittest.main()
