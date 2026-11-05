"""CPU-only contract tests for the opt-in LTX temporal-tiling smoke benchmark."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark-ltx-1080p-tiling.py"
SPEC = importlib.util.spec_from_file_location("ltx_tiling_benchmark", SCRIPT)
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


class TilingBenchmarkTests(unittest.TestCase):
    def test_six_second_1080p_command_is_guarded_and_tiled(self):
        args = BENCH.command(
            Path("/tmp/ltx"), Path("/tmp/model"), Path("/tmp/result.mp4"),
            duration=6, tile_frames=2, tile_spatial=2, tile_overlap=2,
            prompt="camera locked", seed=42)
        self.assertIn("--distilled", args)
        self.assertIn("--low-ram", args)
        self.assertEqual(args[args.index("--width") + 1], "1920")
        self.assertEqual(args[args.index("--height") + 1], "1088")
        self.assertEqual(args[args.index("--frames") + 1], "145")
        self.assertEqual(args[args.index("--tile-frames") + 1], "2")
        self.assertEqual(args[args.index("--tile-spatial") + 1], "2")
        self.assertEqual(args[args.index("--tile-overlap") + 1], "2")
        self.assertEqual(args[args.index("--stage1-steps") + 1], "8")
        self.assertEqual(args[args.index("--stage2-steps") + 1], "3")

    def test_image_to_video_uses_strong_frame_zero_anchor_without_recompression(self):
        image = Path("/tmp/my test image.png")
        argv = BENCH.command(
            Path("/tmp/ltx"), Path("/tmp/model"), Path("/tmp/result.mp4"),
            duration=6, tile_frames=3, tile_spatial=2, tile_overlap=2,
            prompt="Same person from the image", seed=42, image=image)
        self.assertEqual(
            argv[argv.index("--image"):],
            ["--image", str(image), "0", "1.0", "0"])
        self.assertEqual(argv[argv.index("--frames") + 1], "145")

    def test_720p_portrait_untiled_reference_is_true_control(self):
        argv = BENCH.command(
            Path("/tmp/ltx"), Path("/tmp/model"), Path("/tmp/control.mp4"),
            duration=6, tile_frames=1, tile_spatial=1, tile_overlap=2,
            prompt="Same person", seed=42, image=Path("/tmp/Julia_Gerber.png"),
            resolution="720p", aspect_ratio="9:16")
        for flag, expected in (("--width", "704"), ("--height", "1280"),
                               ("--frames", "145"), ("--tile-frames", "1"),
                               ("--tile-spatial", "1"), ("--seed", "42")):
            self.assertEqual(argv[argv.index(flag) + 1], expected)
        self.assertEqual(
            argv[argv.index("--image"):],
            ["--image", "/tmp/Julia_Gerber.png", "0", "1.0", "0"])

    def test_720p_landscape_matches_production_geometry(self):
        argv = BENCH.command(
            Path("ltx"), Path("model"), Path("result.mp4"),
            duration=5, tile_frames=1, tile_spatial=1, tile_overlap=2,
            prompt="test", seed=42, resolution="720p", aspect_ratio="16:9")
        self.assertEqual(argv[argv.index("--width") + 1], "1280")
        self.assertEqual(argv[argv.index("--height") + 1], "704")

    def test_orientation_and_resolution_reject_unsupported_values(self):
        for resolution, aspect in (("540p", "9:16"), ("720p", "4:3")):
            with self.subTest(resolution=resolution, aspect=aspect):
                with self.assertRaisesRegex(ValueError, "Unsupported resolution"):
                    BENCH.command(
                        Path("ltx"), Path("model"), Path("out"),
                        duration=6, tile_frames=1, tile_spatial=1,
                        tile_overlap=2, prompt="test", seed=42,
                        resolution=resolution, aspect_ratio=aspect)

    def test_source_image_validation_and_sha256_are_local(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder, "an image.PNG")
            good.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels")
            BENCH.verify_source_image(good)
            self.assertEqual(len(BENCH.image_digest(good)), 64)
            bad = Path(folder, "invalid.jpg")
            bad.write_bytes(b"hello world")
            with self.assertRaisesRegex(ValueError, "not recognizable"):
                BENCH.verify_source_image(bad)
            missing = Path(folder, "missing.jpg")
            with self.assertRaisesRegex(ValueError, "does not exist"):
                BENCH.verify_source_image(missing)

    def test_image_dry_run_never_launches_a_render(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder, "portrait.png")
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels")
            with mock.patch("sys.argv", ["experiment", "--image", str(image), "--duration", "6"]):
                with mock.patch.object(BENCH.subprocess, "Popen") as spawn:
                    self.assertEqual(BENCH.main(), 0)
                    spawn.assert_not_called()

    def test_duration_is_explicitly_bounded(self):
        with self.assertRaises(ValueError):
            BENCH.command(
                Path("ltx"), Path("model"), Path("out"),
                duration=20, tile_frames=2, tile_spatial=2,
                tile_overlap=2, prompt="test", seed=42)

    def test_memory_pressure_parser_accepts_real_macos_output(self):
        self.assertEqual(
            BENCH.parse_free_percent(
                "The system has 51539607552 (3145728 pages with a page size of 16384).\n"
                "System-wide memory free percentage: 40%\n"),
            40)
        self.assertEqual(
            BENCH.parse_free_percent("System-wide free percentage: 31%\n"),
            31)
        self.assertIsNone(BENCH.parse_free_percent("unsupported format"))

    def test_swap_parser_supports_macos_units(self):
        self.assertAlmostEqual(
            BENCH.parse_swap_gib("total = 10240.00M  used = 7.25G  free = 2.75G"),
            7.25)
        self.assertAlmostEqual(
            BENCH.parse_swap_gib("total = 10240.00M used = 2048.00M free = 8192.00M"),
            2.0)
        self.assertAlmostEqual(
            BENCH.parse_swap_gib("vm.swapusage: total = 10000.00M used: 1.5 GiB (encrypted)"),
            1.5)
        self.assertAlmostEqual(
            BENCH.parse_swap_gib(
                "total = 8192,00M\u00a0 used = 7051,06M\u00a0 "
                "free = 1140,94M\u00a0 (encrypted)"),
            7051.06 / 1024)
        self.assertAlmostEqual(
            BENCH.parse_swap_gib(
                "vm.swapusage: total = 8192,00M\u00a0 used = 7051,06M\u00a0 "
                "free = 1140,94M\u00a0 (encrypted)"),
            7051.06 / 1024)
        self.assertAlmostEqual(BENCH.parse_swap_gib("used = 1,50GiB"), 1.5)
        self.assertEqual(BENCH.parse_swap_gib("used = 0.00M"), 0.0)
        self.assertIsNone(BENCH.parse_swap_gib("unsupported"))

    def test_swap_probe_falls_back_to_another_sysctl_invocation(self):
        from subprocess import CompletedProcess
        first = CompletedProcess(["/usr/sbin/sysctl"], 1, "", "permission denied")
        second = CompletedProcess(["/usr/sbin/sysctl"], 0,
                                  "vm.swapusage: total = 2048.00M used = 512.00M free = 1536.00M", "")
        with mock.patch.object(BENCH.subprocess, "run",
                               side_effect=[first, second]) as run:
            self.assertAlmostEqual(BENCH.read_swap_gib(), 0.5)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(BENCH._SWAP_PROBE_DETAILS, "")

    def test_swap_probe_fails_closed_and_reports_raw_diagnostics(self):
        from subprocess import CompletedProcess
        result = CompletedProcess(["sysctl"], 1, "", "unknown oid")
        with mock.patch.object(BENCH.subprocess, "run",
                               return_value=result) as run:
            self.assertIsNone(BENCH.read_swap_gib())
            self.assertEqual(run.call_count, 4)
            self.assertIn("unknown oid", BENCH._SWAP_PROBE_DETAILS)


    def test_chat_runtime_preflight_detects_listener_without_mutating_it(self):
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        with mock.patch.object(BENCH.socket, "create_connection",
                               return_value=Connection()) as connection:
            self.assertTrue(BENCH.chat_runtime_listening())
            connection.assert_called_once_with(("127.0.0.1", 8000), timeout=1)
        with mock.patch.object(BENCH.socket, "create_connection",
                               side_effect=ConnectionRefusedError):
            self.assertFalse(BENCH.chat_runtime_listening())

    def test_preflight_dry_run_does_not_start_a_process(self):
        with mock.patch("sys.argv", ["experiment", "--duration", "6"]):
            with mock.patch.object(BENCH.subprocess, "Popen") as spawn:
                result = BENCH.main()
        self.assertEqual(result, 0)
        spawn.assert_not_called()

    def test_memory_guard_defaults_are_not_disabled(self):
        self.assertGreaterEqual(BENCH.MIN_START_FREE_PERCENT, 30)
        self.assertGreater(BENCH.MIN_RUNNING_FREE_PERCENT, 0)
        self.assertLess(BENCH.MAX_SWAP_GROWTH_GIB, 5)


if __name__ == "__main__":
    unittest.main()
