import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import video_provider_dispatch
import video_providers_mlx
import video_registry


class VideoMlxRegistryTests(unittest.TestCase):
    def test_registry_keeps_mps_default_and_adds_experimental_q4(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_file = Path(tmp) / "video-models.json"
            with mock.patch.object(video_registry, "REGISTRY_FILE", registry_file):
                data = video_registry.load_registry()

        self.assertEqual(data["default_model"], video_registry.LTX_ID)
        by_id = {item["id"]: item for item in data["models"]}
        self.assertIn(video_registry.LTX_ID, by_id)
        self.assertIn(video_registry.LTX_MLX_Q4_ID, by_id)
        self.assertEqual(by_id[video_registry.LTX_MLX_Q4_ID]["provider"], "ltx-mlx")
        self.assertEqual(by_id[video_registry.LTX_MLX_Q4_ID]["quantization"], "int4")
        self.assertTrue(by_id[video_registry.LTX_MLX_Q4_ID]["experimental"])

    def test_mlx_model_requires_ready_marker_and_embedded_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = video_registry.builtin_mlx_model()
            with mock.patch.object(video_registry, "MLX_MODEL_ROOT", root):
                self.assertFalse(video_registry.local_files_available(model))
                model_dir = root / video_registry.LTX_MLX_Q4_ID
                model_dir.mkdir(parents=True)
                (model_dir / "embedded_config.json").write_text("{}")
                self.assertFalse(video_registry.local_files_available(model))
                (model_dir / video_registry.MLX_READY_MARKER).touch()
                self.assertTrue(video_registry.local_files_available(model))


class VideoMlxProviderTests(unittest.TestCase):
    def params(self, quality="standard"):
        return {
            "prompt": "A red ball rolls",
            "quality": quality,
            "resolution": "720p" if quality != "preview" else "preview",
            "duration": 5 if quality != "preview" else 2,
            "fps": 24 if quality != "preview" else 8,
            "frames": 121 if quality != "preview" else 17,
            "aspect_ratio": "16:9",
            "width": 1280 if quality != "preview" else 384,
            "height": 704 if quality != "preview" else 256,
            "seed": 42,
            "first_frame": None,
        }

    def test_distilled_q4_command_matches_nobby_8_plus_3_profile(self):
        model = video_registry.builtin_mlx_model()
        with mock.patch.object(video_providers_mlx, "LTX_MLX_CLI", Path("/runtime/ltx-2-mlx")), \
             mock.patch.object(video_registry, "model_path", return_value=Path("/models/ltx-q4")), \
             mock.patch.object(video_providers_mlx, "DEFAULT_LOW_RAM", True):
            command = video_providers_mlx._command(
                model, self.params(), Path("/tmp/out.mp4")
            )

        self.assertEqual(command[0:3], ["/runtime/ltx-2-mlx", "generate", "--distilled"])
        self.assertEqual(command[command.index("--stage1-steps") + 1], "8")
        self.assertEqual(command[command.index("--stage2-steps") + 1], "3")
        self.assertEqual(command[command.index("--model") + 1], "/models/ltx-q4")
        self.assertNotIn("--gemma", command)
        self.assertIn("--low-ram", command)

    def test_preview_uses_one_plus_one_steps(self):
        model = video_registry.builtin_mlx_model()
        with mock.patch.object(video_registry, "model_path", return_value=Path("/models/ltx-q4")):
            command = video_providers_mlx._command(
                model, self.params("preview"), Path("/tmp/out.mp4")
            )
        self.assertEqual(command[command.index("--stage1-steps") + 1], "1")
        self.assertEqual(command[command.index("--stage2-steps") + 1], "1")

    def test_i2v_uses_native_target_geometry(self):
        model = video_registry.builtin_mlx_model()
        params = self.params()
        params.update({
            "first_frame": "/managed/square.png",
            "width": 1024,
            "height": 1024,
            "resize_mode": "contain",
        })
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            source = Path(tmp) / "source.png"
            source.touch()

            def prepare(_source, width, height, _mode, destination):
                self.assertEqual((width, height), (1024, 1024))
                destination.write_bytes(b"png")
                return {
                    "source_width": 1024,
                    "source_height": 1024,
                    "target_width": width,
                    "target_height": height,
                    "resize_mode": "contain",
                }

            def run(_command, **_kwargs):
                output.write_bytes(b"mp4")

            with mock.patch.object(video_providers_mlx, "PERSISTENT_WORKER", False), \
                 mock.patch.object(video_providers_mlx, "availability", return_value=(True, "ok")), \
                 mock.patch.object(video_providers_mlx, "validate_first_frame", return_value=source), \
                 mock.patch.object(video_providers_mlx, "_prepare_first_frame", side_effect=prepare), \
                 mock.patch.object(video_providers_mlx, "_run_process", side_effect=run), \
                 mock.patch.object(video_providers_mlx, "_probe_video", return_value={
                     "frames": 121, "width": 1024, "height": 1024,
                     "fps": 24, "duration": 5, "audio": True,
                 }), \
                 mock.patch.object(video_registry, "model_path", return_value=Path("/models/ltx-q4")):
                result = video_providers_mlx.generate(
                    model, params, output, cancel_event=threading.Event()
                )

        self.assertEqual(result["backend"], "mlx")
        self.assertEqual(result["conditioning_width"], 1024)
        self.assertEqual(result["conditioning_height"], 1024)
        self.assertFalse(result["runtime_reused"])


class VideoProviderDispatchTests(unittest.TestCase):
    def test_dispatches_mlx_and_mps_independently(self):
        mlx_model = video_registry.builtin_mlx_model()
        mps_model = video_registry.builtin_model()
        with mock.patch.object(video_provider_dispatch.mlx, "availability", return_value=(True, "mlx")) as mlx_available, \
             mock.patch.object(video_provider_dispatch.mps, "availability", return_value=(True, "mps")) as mps_available:
            self.assertEqual(video_provider_dispatch.availability(mlx_model), (True, "mlx"))
            self.assertEqual(video_provider_dispatch.availability(mps_model), (True, "mps"))
        mlx_available.assert_called_once_with(mlx_model)
        mps_available.assert_called_once_with(mps_model)

    def test_launchd_uses_provider_dispatch_entrypoint(self):
        template = Path("launchd/templates/de.nobby.mlx-video.plist.template").read_text()
        self.assertIn("video_service_dispatch:app", template)
        self.assertIn("LTX_MLX_LOW_RAM", template)
        self.assertNotIn("LTX_MLX_GEMMA_DIR", template)

    def test_setup_uses_pack_local_gemma4_and_pinned_upstream(self):
        setup = Path("scripts/setup-ltx-video-mlx").read_text()
        self.assertIn("1724ca673d59f023a8a95efee06e5d36d61c2765", setup)
        self.assertIn("text_encoder.safetensors", setup)
        self.assertIn("text_encoder_config.json", setup)
        self.assertNotIn("gemma-3-12b-it-4bit", setup)


if __name__ == "__main__":
    unittest.main()
