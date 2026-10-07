import unittest
from unittest import mock

from agent import talking_photo_routes


class TalkingPhotoRouteQualityTests(unittest.TestCase):
    def test_request_defaults_to_quality_on_quality_branch(self):
        request = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
        )
        self.assertEqual(request.engine, "quality")

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
             mock.patch.object(talking_photo_routes.talking_photo_quality, "provider_health", return_value=quality):
            status = talking_photo_routes.provider_status()

        self.assertTrue(status["ready"])
        self.assertEqual(status["provider"], "musetalk-mac")
        self.assertEqual(status["default_engine"], "quality")
        self.assertTrue(status["quality_available"])
        self.assertEqual(status["providers"]["quality"]["provider"], "ltx-2.5-mlx-a2v")


if __name__ == "__main__":
    unittest.main()
