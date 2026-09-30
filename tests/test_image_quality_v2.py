import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import image_providers


class MFluxMemoryPolicyTests(unittest.TestCase):
    def policy_env(self, **extra):
        values = {
            "MLX_IMAGE_MFLUX_MODE": "auto",
            "MLX_IMAGE_MFLUX_PERFORMANCE_HEADROOM_GB": "16",
            "MLX_IMAGE_MFLUX_BALANCED_HEADROOM_GB": "8",
            "MLX_IMAGE_MFLUX_PERFORMANCE_CACHE_GB": "8",
            "MLX_IMAGE_MFLUX_BALANCED_CACHE_GB": "4",
            "MLX_IMAGE_MFLUX_LOW_RAM_CACHE_GB": "2",
        }
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=False)

    def test_auto_uses_performance_mode_with_large_normal_headroom(self):
        with self.policy_env():
            policy = image_providers.mflux_memory_policy({
                "pressure": "normal",
                "headroom_gb": 22.0,
            })
        self.assertEqual(policy["mode"], "performance")
        self.assertFalse(policy["low_ram"])
        self.assertEqual(policy["cache_gb"], 8)

    def test_auto_uses_balanced_low_ram_mode_for_medium_headroom(self):
        with self.policy_env():
            policy = image_providers.mflux_memory_policy({
                "pressure": "normal",
                "headroom_gb": 11.0,
            })
        self.assertEqual(policy["mode"], "balanced")
        self.assertTrue(policy["low_ram"])
        self.assertEqual(policy["cache_gb"], 4)

    def test_auto_uses_low_ram_mode_under_memory_pressure(self):
        with self.policy_env():
            policy = image_providers.mflux_memory_policy({
                "pressure": "elevated",
                "headroom_gb": 25.0,
            })
        self.assertEqual(policy["mode"], "low-ram")
        self.assertTrue(policy["low_ram"])
        self.assertEqual(policy["cache_gb"], 2)

    def test_unknown_memory_state_stays_conservative(self):
        with self.policy_env():
            policy = image_providers.mflux_memory_policy({
                "pressure": "unknown",
                "headroom_gb": None,
            })
        self.assertEqual(policy["mode"], "balanced")
        self.assertTrue(policy["low_ram"])

    def test_explicit_performance_override_is_respected(self):
        with self.policy_env(MLX_IMAGE_MFLUX_MODE="performance"):
            policy = image_providers.mflux_memory_policy({
                "pressure": "critical",
                "headroom_gb": 1.0,
            })
        self.assertEqual(policy["mode"], "performance")
        self.assertFalse(policy["low_ram"])

    def test_mflux_command_omits_low_ram_in_performance_mode(self):
        model = {
            "model_family": "z-image-turbo",
            "base_model": "schnell",
            "quantization": "4-bit",
            "loras": [],
        }
        params = {
            "prompt": "A clean test image",
            "width": 512,
            "height": 512,
            "steps": 6,
            "seed": 7,
            "guidance": 0,
        }
        with mock.patch.object(
            image_providers,
            "model_directory",
            return_value=Path("/tmp/model"),
        ), mock.patch.object(
            image_providers,
            "mflux_memory_policy",
            return_value={"mode": "performance", "low_ram": False, "cache_gb": 8},
        ):
            command = image_providers.mflux_command(
                model,
                params,
                Path("/tmp/output.png"),
            )
        self.assertNotIn("--low-ram", command)
        cache_index = command.index("--mlx-cache-limit-gb")
        self.assertEqual(command[cache_index + 1], "8")


class QualityPlusTests(unittest.TestCase):
    def test_quality_upscale_is_skipped_when_runtime_is_unavailable(self):
        params = {"quality": "quality", "width": 512, "height": 512}
        with mock.patch.object(
            image_providers,
            "quality_upscale_available",
            return_value=False,
        ), mock.patch.dict(
            os.environ,
            {"MLX_IMAGE_QUALITY_UPSCALE": "auto"},
            clear=False,
        ):
            used = image_providers._maybe_quality_upscale(
                params,
                Path("/tmp/base.png"),
            )
        self.assertFalse(used)
        self.assertEqual((params["width"], params["height"]), (512, 512))

    def test_required_quality_upscale_fails_when_runtime_is_missing(self):
        params = {"quality": "quality", "width": 512, "height": 512}
        with mock.patch.object(
            image_providers,
            "quality_upscale_available",
            return_value=False,
        ), mock.patch.dict(
            os.environ,
            {"MLX_IMAGE_QUALITY_UPSCALE": "required"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                image_providers._maybe_quality_upscale(
                    params,
                    Path("/tmp/base.png"),
                )

    def test_quality_upscale_replaces_base_image_and_updates_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "base.png"
            Image.new("RGB", (32, 24), "white").save(source)
            params = {"quality": "quality", "width": 32, "height": 24}

            def command(source_path, output_path, *, preset="photo-2x", tile=0):
                return [
                    "fake-realesrgan",
                    "-i", str(source_path),
                    "-o", str(output_path),
                    "-s", "2",
                ]

            class Process:
                returncode = 0

                def __init__(self):
                    self.stdout = io.StringIO("100%\n")

                def poll(self):
                    return 0

            def popen(command_line, **_kwargs):
                source_path = Path(command_line[command_line.index("-i") + 1])
                output_path = Path(command_line[command_line.index("-o") + 1])
                with Image.open(source_path) as image:
                    image.resize((image.width * 2, image.height * 2)).save(output_path)
                return Process()

            progress = []
            with mock.patch.object(
                image_providers,
                "quality_upscale_available",
                return_value=True,
            ), mock.patch.object(
                image_providers,
                "realesrgan_command",
                side_effect=command,
            ), mock.patch.object(
                image_providers.subprocess,
                "Popen",
                side_effect=popen,
            ), mock.patch.dict(
                os.environ,
                {"MLX_IMAGE_QUALITY_UPSCALE": "auto"},
                clear=False,
            ):
                used = image_providers._maybe_quality_upscale(
                    params,
                    source,
                    progress_callback=progress.append,
                )

            self.assertTrue(used)
            self.assertEqual((params["width"], params["height"]), (64, 48))
            self.assertTrue(params["quality_upscale"])
            self.assertEqual(params["upscale_preset"], "photo-2x")
            with Image.open(source) as image:
                self.assertEqual(image.size, (64, 48))
            self.assertTrue(any(event.get("phase") == "upscaling" for event in progress))

    def test_standard_quality_never_triggers_quality_plus(self):
        params = {"quality": "standard", "width": 512, "height": 512}
        with mock.patch.object(
            image_providers,
            "quality_upscale_available",
        ) as available:
            used = image_providers._maybe_quality_upscale(
                params,
                Path("/tmp/base.png"),
            )
        self.assertFalse(used)
        available.assert_not_called()


if __name__ == "__main__":
    unittest.main()
