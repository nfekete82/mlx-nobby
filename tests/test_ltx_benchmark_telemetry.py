import runpy
import unittest
from pathlib import Path


BENCHMARK = runpy.run_path(str(Path("scripts/benchmark-ltx-video.py")))


class LtxBenchmarkTelemetryTests(unittest.TestCase):
    def test_powermetrics_thermal_trace_tracks_first_peak_last_and_counts(self):
        parse = BENCHMARK["_parse_powermetrics_thermal"]
        trace = parse(
            "\n".join(
                [
                    "Current pressure level: Nominal",
                    "Current pressure level: Moderate",
                    "Current pressure level: Heavy",
                    "Current pressure level: Heavy",
                ]
            )
        )

        self.assertEqual(trace["samples"], 4)
        self.assertEqual(trace["first"], "Nominal")
        self.assertEqual(trace["peak"], "Heavy")
        self.assertEqual(trace["last"], "Heavy")
        self.assertEqual(
            trace["counts"],
            {"Nominal": 1, "Moderate": 1, "Heavy": 2},
        )
        self.assertEqual(BENCHMARK["_thermal_flow"](trace), "N→H→H")
        self.assertEqual(BENCHMARK["_thermal_trace_compact"](trace), "N1/M1/H2")

    def test_swap_parser_accepts_gigabytes_and_megabytes(self):
        parse = BENCHMARK["_swap_used"]
        self.assertEqual(
            parse("total = 16.00G  used = 14.50G  free = 1.50G"),
            int(14.5 * (1024 ** 3)),
        )
        self.assertEqual(
            parse("total = 16384.00M  used = 15360.00M  free = 1024.00M"),
            15360 * (1024 ** 2),
        )

    def test_benchmark_exposes_direct_thermal_sampling_mode(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertIn('"--thermal"', source)
        self.assertIn('subprocess.run(["sudo", "-v"]', source)
        self.assertIn('"/usr/bin/powermetrics"', source)
        self.assertIn('"thermal_trace": thermal_trace', source)
        self.assertIn("Thermal = powermetrics Start→Peak→Ende", source)

    def test_powermetrics_keeps_sudo_ticket_and_does_not_touch_terminal_input(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertNotIn("start_new_session=True", source)
        self.assertIn("stdin=subprocess.DEVNULL", source)
        self.assertIn("process.send_signal(signal.SIGINT)", source)
        self.assertNotIn("os.killpg(process.pid, signal.SIGINT)", source)

    def test_reference_baseline_matches_only_canonical_mlx_run(self):
        baseline = BENCHMARK["REFERENCE_BASELINE"]
        reference = BENCHMARK["_reference_baseline_seconds"]
        delta = BENCHMARK["_baseline_delta_text"]
        item = {
            "model": "ltx-2.5-mlx-q4",
            "quality": "standard",
            "duration": 5,
            "fps": 24,
            "aspect_ratio": "16:9",
            "seed": 42,
            "wall_seconds": 140.8,
        }
        self.assertEqual(baseline["wall_seconds"], 141.5)
        self.assertEqual(reference(item), 141.5)
        self.assertEqual(delta(item), "-0.7s")

        changed = dict(item, fps=8)
        self.assertIsNone(reference(changed))
        self.assertEqual(delta(changed), "—")

    def test_table_uses_explicit_blank_lines_instead_of_embedded_terminal_newlines(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertIn('print()\n    print("Ergebnisse")', source)
        self.assertIn('print()\n            print(f"[{repeat}/{repeat_count}] {model}"', source)


if __name__ == "__main__":
    unittest.main()
