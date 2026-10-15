import unittest
from unittest import mock

from pydantic import ValidationError

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

    def test_request_defaults_to_distilled_with_natural_motion(self):
        request = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
        )
        self.assertEqual(request.engine, "ltx-distilled")
        self.assertEqual(request.motion, "natural")
        direct = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
            engine="ltx",
        )
        self.assertEqual(direct.engine, "ltx")
        beta = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo", engine="ltx-distilled",
        )
        self.assertEqual(beta.engine, "ltx-distilled")

    def test_route_dispatches_distilled_as_direct_ltx_default(self):
        handlers = {}
        class App:
            routes = []
            def get(self, path, **kwargs):
                def decorate(handler):
                    handlers[("GET", path)] = handler
                    return handler
                return decorate
            def post(self, path, **kwargs):
                def decorate(handler):
                    handlers[("POST", path)] = handler
                    return handler
                return decorate
        with mock.patch.object(talking_photo_routes.talking_photo, "recover_jobs"):
            talking_photo_routes.install_routes(App())
        req = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo",
        )
        with mock.patch.object(talking_photo_quality, "create_job", return_value={"id": "test"}) as create:
            result = handlers[("POST", "/api/talking-photo/jobs")](req)
        self.assertEqual(result["id"], "test")
        payload = req.model_dump()
        payload.pop("engine")
        create.assert_called_once_with(payload, ltx_only=True, distilled=True)

    def test_audio_lead_in_is_opt_in_and_strictly_validated(self):
        base = {"image_data_url": "data:image/png;base64," + "A" * 32, "text": "Guten Morgen!"}
        self.assertEqual(talking_photo_routes.TalkingPhotoRequest(**base).lead_in_ms, 0)
        self.assertEqual(
            talking_photo_routes.TalkingPhotoRequest(**base, lead_in_ms=500).lead_in_ms, 500
        )
        for value in (-1, 250, 501, 1000, "0.5"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                talking_photo_routes.TalkingPhotoRequest(**base, lead_in_ms=value)

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
        self.assertEqual(status["default_engine"], "ltx-distilled")
        self.assertTrue(status["quality_available"])
        self.assertTrue(status["ltx_available"])
        self.assertEqual(status["providers"]["quality"]["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(status["providers"]["ltx"]["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(status["providers"]["ltx-distilled"]["provider"], "ltx-2.5-mlx-a2v")
        self.assertTrue(status["ltx_distilled_available"])


if __name__ == "__main__":
    unittest.main()
