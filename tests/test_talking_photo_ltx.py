import unittest
from unittest import mock

from agent import talking_photo_ltx


class TalkingPhotoLtxTests(unittest.TestCase):
    def test_quality_frames_cover_audio_on_ltx_grid(self):
        frames, duration = talking_photo_ltx.quality_frames(3.0)
        self.assertEqual(frames, 73)
        self.assertAlmostEqual(duration, 73 / 24)
        self.assertGreaterEqual(duration, 3.0)
        self.assertEqual((frames - 1) % 8, 0)

    def test_quality_frames_reject_long_beta_audio(self):
        with self.assertRaisesRegex(RuntimeError, "maximal 5 Sekunden"):
            talking_photo_ltx.quality_frames(5.01)

    def test_target_dimensions_are_conservative_and_orientation_aware(self):
        self.assertEqual(talking_photo_ltx.target_dimensions(900, 1400), (512, 704))
        self.assertEqual(talking_photo_ltx.target_dimensions(1400, 900), (704, 512))
        self.assertEqual(talking_photo_ltx.target_dimensions(1000, 1000), (640, 640))

    def test_provider_health_requires_runtime_runner_and_model(self):
        fake_python = mock.Mock()
        fake_python.is_file.return_value = True
        fake_runner = mock.Mock()
        fake_runner.is_file.return_value = True
        fake_model = mock.Mock()
        fake_model.is_dir.return_value = True
        embedded = mock.Mock()
        embedded.is_file.return_value = True
        fake_model.__truediv__ = mock.Mock(return_value=embedded)

        with mock.patch.object(talking_photo_ltx, "RUNTIME_PYTHON", fake_python), \
             mock.patch.object(talking_photo_ltx, "RUNNER", fake_runner), \
             mock.patch.object(talking_photo_ltx, "MODEL_DIR", fake_model), \
             mock.patch("agent.talking_photo_ltx.os.access", return_value=True):
            health = talking_photo_ltx.provider_health()

        self.assertTrue(health["ready"])
        self.assertEqual(health["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(health["max_audio_seconds"], 5.0)


if __name__ == "__main__":
    unittest.main()
