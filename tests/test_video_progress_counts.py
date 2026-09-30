import unittest
from pathlib import Path
from unittest import mock

import video_provider_dispatch


class VideoProgressCountTests(unittest.TestCase):
    def test_mlx_progress_restores_cumulative_8_plus_3_steps(self):
        params = {"quality": "standard", "steps": 11}
        event = video_provider_dispatch._mlx_progress_event(
            params,
            {"phase": "denoising", "progress": 0.081818},
        )
        self.assertEqual(event["step"], 1)
        self.assertEqual(event["total_steps"], 11)

        event = video_provider_dispatch._mlx_progress_event(
            params,
            {"phase": "denoising", "progress": 0.736364},
        )
        self.assertEqual(event["step"], 9)
        self.assertEqual(event["total_steps"], 11)

        event = video_provider_dispatch._mlx_progress_event(
            params,
            {"phase": "denoising", "progress": 0.9},
        )
        self.assertEqual(event["step"], 11)
        self.assertEqual(event["total_steps"], 11)

    def test_preview_progress_uses_two_total_steps(self):
        event = video_provider_dispatch._mlx_progress_event(
            {"quality": "preview", "steps": 2},
            {"phase": "denoising", "progress": 0.45},
        )
        self.assertEqual(event["step"], 1)
        self.assertEqual(event["total_steps"], 2)

    def test_existing_provider_step_metadata_is_preserved(self):
        original = {
            "phase": "denoising",
            "progress": 0.5,
            "step": 4,
            "total_steps": 8,
        }
        self.assertEqual(
            video_provider_dispatch._mlx_progress_event(
                {"quality": "standard", "steps": 11}, original,
            ),
            original,
        )

    def test_service_dispatch_uses_validated_profile_steps_for_completion(self):
        source = Path("video_service_dispatch.py").read_text()
        self.assertIn('steps = int(payload.steps)', source)
        self.assertIn('return 2 if payload.quality == "preview" else 11', source)
        self.assertIn('service._job_total_steps = _job_total_steps', source)

    def test_reset_mlx_warm_runtime_reports_previous_state_and_stops_worker(self):
        with mock.patch.object(
            video_provider_dispatch.mlx,
            "warm_runtime_status",
            return_value={"loaded": True, "requests_completed": 2},
        ), mock.patch.object(
            video_provider_dispatch.mlx,
            "shutdown_warm_runtime",
        ) as shutdown:
            before = video_provider_dispatch.reset_mlx_warm_runtime()

        self.assertTrue(before["loaded"])
        self.assertEqual(before["requests_completed"], 2)
        shutdown.assert_called_once_with()

    def test_service_dispatch_exposes_idle_only_mlx_reset_endpoint(self):
        source = Path("video_service_dispatch.py").read_text()
        self.assertIn('@app.post("/runtime/mlx/reset")', source)
        self.assertIn('if job.get("status") in service.ACTIVE', source)
        self.assertIn('reset_mlx_warm_runtime()', source)
        self.assertIn('"was_loaded": bool(before.get("loaded"))', source)

    def test_benchmark_supports_forced_cold_warm_cold_sequence(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertIn('"--cold-warm-cold"', source)
        self.assertIn('repeat_count = 3', source)
        self.assertIn('if args.cold_warm_cold and repeat == 2:', source)
        self.assertGreaterEqual(source.count('reset_mlx_runtime(base_url)'), 2)


if __name__ == "__main__":
    unittest.main()
