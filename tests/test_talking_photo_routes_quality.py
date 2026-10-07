import unittest
from unittest import mock

from agent import talking_photo_routes
from agent import talking_photo_quality


class TalkingPhotoRouteQualityTests(unittest.TestCase):
    def test_quality_requires_both_renderers_and_reports_missing_lipsync_runtime(self):
        for ready in (True, False):
            with self.subTest(ready=ready), \
                 mock.patch.object(talking_photo_quality.talking_photo_ltx, "provider_health", return_value={"ready": True, "provider": "ltx-2.5-mlx-a2v"}), \
                 mock.patch.object(talking_photo_quality.talking_photo, "provider_health", return_value={"ready": ready, "provider": "musetalk-mac", "detail": "missing", "setup_command": "./scripts/setup-musetalk-mac"}):
                health = talking_photo_quality.provider_health()
                self.assertEqual(health["ready"], ready)
                self.assertEqual(health["provider"], "ltx-2.5-mlx-a2v")
                self.assertEqual(health["lipsync_provider"], "musetalk-mac")
                if not ready:
                    self.assertEqual(health["setup_command"], "./scripts/setup-musetalk-mac")

    def test_request_defaults_to_quality_on_quality_branch(self):
        request = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
        )
        self.assertEqual(request.engine, "quality")
        direct = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
            engine="ltx",
        )
        self.assertEqual(direct.engine, "ltx")

    def test_direct_ltx_health_does_not_require_musetalk(self):
        native = {
            "ready": True,
            "provider": "ltx-2.5-mlx-a2v",
            "device": "mlx/metal",
            "setup_command": "./scripts/setup-ltx-video-mlx",
            "detail": None,
        }
        with mock.patch.object(
            talking_photo_quality.talking_photo_ltx,
            "provider_health",
            return_value=native,
        ), mock.patch.object(
            talking_photo_quality.talking_photo,
            "provider_health",
        ) as musetalk:
            health = talking_photo_quality.direct_provider_health()

        self.assertTrue(health["ready"])
        self.assertEqual(health["provider"], "ltx-2.5-mlx-a2v")
        musetalk.assert_not_called()

    def test_provider_status_keeps_fast_top_level_contract(self):
        fast = {
            "ready": True,
            "provider": "musetalk-mac",
            "device": "mps",
            "setup_command": "./scripts/setup-musetalk-mac",
            "detail": None,
        }
        quality = {
            "ready": True,
            "provider": "ltx-2.5-mlx-a2v",
            "device": "mlx/metal",
            "setup_command": "./scripts/setup-ltx-video-mlx",
            "detail": None,
        }
        with mock.patch.object(talking_photo_routes.talking_photo, "provider_health", return_value=fast), \
             mock.patch.object(talking_photo_routes.talking_photo_quality, "provider_health", return_value=quality), \
             mock.patch.object(talking_photo_routes.talking_photo_quality, "direct_provider_health", return_value=quality):
            status = talking_photo_routes.provider_status()

        self.assertTrue(status["ready"])
        self.assertEqual(status["provider"], "musetalk-mac")
        self.assertEqual(status["default_engine"], "quality")
        self.assertTrue(status["quality_available"])
        self.assertTrue(status["ltx_available"])
        self.assertEqual(status["providers"]["quality"]["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(status["providers"]["ltx"]["provider"], "ltx-2.5-mlx-a2v")


if __name__ == "__main__":
    unittest.main()
