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
        maximum = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo", engine="ltx-max",
        )
        self.assertEqual(maximum.engine, "ltx-max")

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
        maximum = talking_photo_routes.TalkingPhotoRequest(
            image_data_url="data:image/png;base64," + "A" * 32,
            text="Hallo", engine="ltx-max",
        )
        with mock.patch.object(talking_photo_quality, "create_job", return_value={"id": "max"}) as max_create:
            response = handlers[("POST", "/api/talking-photo/jobs")](maximum)
        self.assertEqual(response["id"], "max")
        max_payload = maximum.model_dump()
        max_payload.pop("engine")
        max_create.assert_called_once_with(max_payload, ltx_only=True, stage1_steps=30)

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

    def test_provider_status_is_ltx_only_without_musetalk_probe(self):
        native = {
            "ready": True, "provider": "ltx-2.5-mlx-a2v",
            "device": "mlx/metal",
            "setup_command": "./scripts/setup-ltx-video-mlx", "detail": None,
        }
        with mock.patch.object(talking_photo_routes.talking_photo, "provider_health") as muse, \
             mock.patch.object(talking_photo_routes.talking_photo_quality, "provider_health") as hybrid, \
             mock.patch.object(talking_photo_routes.talking_photo_quality, "direct_provider_health", return_value=native):
            status = talking_photo_routes.provider_status()
        muse.assert_not_called()
        hybrid.assert_not_called()
        self.assertTrue(status["ready"])
        self.assertEqual(status["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(status["default_engine"], "ltx-distilled")
        self.assertEqual(set(status["providers"]), {"ltx", "ltx-distilled", "ltx-max"})
        self.assertTrue(status["ltx_available"])
        self.assertTrue(status["ltx_distilled_available"])
        self.assertTrue(status["ltx_max_available"])

    def test_legacy_musetalk_engines_rejected(self):
        base = {"image_data_url": "data:image/png;base64," + "A" * 32, "text": "Hallo"}
        for legacy in ("fast", "quality"):
            with self.subTest(engine=legacy), self.assertRaises(ValidationError):
                talking_photo_routes.TalkingPhotoRequest(**base, engine=legacy)


if __name__ == "__main__":
    unittest.main()
