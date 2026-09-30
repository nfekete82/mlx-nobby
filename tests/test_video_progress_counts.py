import unittest
from types import SimpleNamespace

import video_provider_dispatch
import video_service_dispatch


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

    def test_service_uses_validated_profile_steps_for_completion(self):
        standard = SimpleNamespace(steps=11, quality="standard")
        preview = SimpleNamespace(steps=2, quality="preview")
        self.assertEqual(video_service_dispatch._job_total_steps(standard), 11)
        self.assertEqual(video_service_dispatch._job_total_steps(preview), 2)


if __name__ == "__main__":
    unittest.main()
