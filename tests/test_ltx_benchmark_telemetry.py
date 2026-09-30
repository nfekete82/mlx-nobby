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

    def test_powermetrics_keeps_sudo_ticket_tty_and_stops_child_safely(self):
        source = Path("scripts/benchmark-ltx-video.py").read_text()
        self.assertNotIn("start_new_session=True", source)
        self.assertIn("process.send_signal(signal.SIGINT)", source)
        self.assertNotIn("os.killpg(process.pid, signal.SIGINT)", source)


if __name__ == "__main__":
    unittest.main()
