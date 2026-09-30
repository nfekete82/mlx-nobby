import tempfile
import unittest
from pathlib import Path
from unittest import mock

import quality_profiles
import video_provider_dispatch
import video_providers_wan
import video_registry


class WanRegistryTests(unittest.TestCase):
    def test_registry_adds_wan_without_changing_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_file = Path(tmp) / "video-models.json"
            with mock.patch.object(video_registry, "REGISTRY_FILE", registry_file):
                data = video_registry.load_registry()

        self.assertEqual(data["default_model"], video_registry.LTX_ID)
        by_id = {item["id"]: item for item in data["models"]}
        wan = by_id[video_registry.WAN_MLX_Q8_ID]
        self.assertEqual(wan["provider"], "wan-mlx")
        self.assertEqual(wan["model_family"], "wan2.2-ti2v")
        self.assertEqual(wan["quantization"], "int8")
        self.assertNotIn("audio", wan["capabilities"])
        self.assertTrue(wan["experimental"])

    def test_wan_requires_ready_marker_and_runtime_files(self):
        model = video_registry.builtin_wan_model()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / video_registry.WAN_MLX_Q8_ID
            model_dir.mkdir()
            with mock.patch.object(video_registry, "WAN_MLX_MODEL_ROOT", root):
                self.assertFalse(video_registry.local_files_available(model))
                for name in video_registry.WAN_REQUIRED_FILES:
                    (model_dir / name).touch()
                self.assertTrue(video_registry.local_files_available(model))


class WanProfileTests(unittest.TestCase):
    def test_profiles_keep_native_720p_and_scale_steps(self):
        model = video_registry.builtin_wan_model()
        fast = quality_profiles.resolve_video_profile(model, "fast")
        standard = quality_profiles.resolve_video_profile(model, "standard")
        quality = quality_profiles.resolve_video_profile(model, "quality")
        self.assertEqual(fast["resolution"], "720p")
        self.assertEqual((fast["steps"], standard["steps"], quality["steps"]), (10, 20, 40))
        self.assertEqual(standard["pipeline"], "single-model-unipc")


class WanProviderTests(unittest.TestCase):
    def params(self):
        return {
            "prompt": "A red sports car in rain",
            "quality": "standard",
            "resolution": "720p",
            "duration": 5,
            "fps": 24,
            "frames": 121,
            "aspect_ratio": "16:9",
            "width": 1280,
            "height": 704,
            "steps": 20,
            "seed": 42,
            "first_frame": None,
        }

    def test_command_uses_pinned_native_wan_module(self):
        model = video_registry.builtin_wan_model()
        with mock.patch.object(video_providers_wan, "WAN_PYTHON", Path("/runtime/python")), \
             mock.patch.object(video_providers_wan, "WAN_MODEL_ROOT", Path("/models")):
            command = video_providers_wan._command(model, self.params(), Path("/tmp/out.mp4"))

        self.assertEqual(command[:3], ["/runtime/python", "-m", "mlx_video.models.wan_2.generate"])
        self.assertEqual(command[command.index("--model-dir") + 1], "/models/wan2.2-ti2v-5b-mlx-q8")
        self.assertEqual(command[command.index("--steps") + 1], "20")
        self.assertEqual(command[command.index("--guide-scale") + 1], "5.0")
        self.assertEqual(command[command.index("--scheduler") + 1], "unipc")
        self.assertEqual(command[command.index("--num-frames") + 1], "121")
        self.assertNotIn("--image", command)

    def test_preview_is_deliberately_rejected(self):
        model = video_registry.builtin_wan_model()
        params = self.params()
        params["quality"] = "preview"
        with self.assertRaisesRegex(ValueError, "Preview"):
            video_providers_wan._command(model, params, Path("/tmp/out.mp4"))

    def test_dispatch_routes_wan_independently(self):
        model = video_registry.builtin_wan_model()
        with mock.patch.object(video_provider_dispatch.wan, "availability", return_value=(True, "wan")) as available:
            self.assertEqual(video_provider_dispatch.availability(model), (True, "wan"))
        available.assert_called_once_with(model)

    def test_setup_pins_runtime_model_and_licenses(self):
        setup = Path("scripts/setup-wan22-video-mlx").read_text()
        self.assertIn("87db56a51758fefb748a359b90a5283bb8ba4837", setup)
        self.assertIn("9624723c94ddf509832555c45e223a035baa7d1c", setup)
        self.assertIn("Anes1032/Wan2.2-TI2V-5B-mlx-q8", setup)
        self.assertIn("MIT", setup)
        self.assertIn("Apache-2.0", setup)

    def test_launchd_exposes_wan_runtime_paths(self):
        template = Path("launchd/templates/de.nobby.mlx-video.plist.template").read_text()
        self.assertIn("WAN_MLX_RUNTIME_ROOT", template)
        self.assertIn("WAN_MLX_MODEL_ROOT", template)


if __name__ == "__main__":
    unittest.main()
