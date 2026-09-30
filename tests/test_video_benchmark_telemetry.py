import importlib.util
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path("scripts/benchmark-ltx-video.py")
SPEC = importlib.util.spec_from_file_location("benchmark_ltx_video", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class VideoBenchmarkTelemetryTests(unittest.TestCase):
    def test_vm_stat_ram_used_matches_service_accounting(self):
        output = """Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 1000.\nPages active: 100.\nPages inactive: 50.\nPages speculative: 5.\nPages wired down: 25.\nPages occupied by compressor: 10.\n"""
        self.assertEqual(benchmark._vm_stat_ram_used(output), 190 * 16384)

    def test_swap_usage_parser_handles_gigabytes(self):
        output = "total = 20.00G  used = 15.50G  free = 4.50G  (encrypted)"
        self.assertEqual(benchmark._swap_used(output), int(15.5 * 1024 ** 3))

    def test_pmset_thermal_parser_reports_limits_not_temperature(self):
        output = """Note: No thermal warning level has been recorded\nNote: No performance warning level has been recorded\nCPU_Speed_Limit = 85\nScheduler_Limit = 90\nAvailable_CPUs = 12\n"""
        parsed = benchmark._parse_thermal_limits(output)
        self.assertEqual(parsed["cpu_speed_limit"], 85)
        self.assertEqual(parsed["scheduler_limit"], 90)
        self.assertEqual(parsed["available_cpus"], 12)
        self.assertFalse(parsed["thermal_warning_recorded"])
        self.assertFalse(parsed["performance_warning_recorded"])

    def test_system_snapshot_is_best_effort_and_parses_pressure(self):
        outputs = {
            ("vm_stat",): "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages active: 10.\n",
            ("sysctl", "-n", "vm.swapusage"): "total = 10.00G used = 3.00G free = 7.00G",
            ("pmset", "-g", "therm"): "CPU_Speed_Limit = 100\nScheduler_Limit = 100\nAvailable_CPUs = 16",
            ("sysctl", "-n", "kern.memorystatus_vm_pressure_level"): "1",
        }
        with mock.patch.object(benchmark, "_command_output", side_effect=lambda command: outputs.get(tuple(command), "")):
            snapshot = benchmark.system_snapshot()
        self.assertEqual(snapshot["ram_used_bytes"], 10 * 4096)
        self.assertEqual(snapshot["swap_used_bytes"], 3 * 1024 ** 3)
        self.assertEqual(snapshot["memory_pressure_level"], 1)
        self.assertEqual(snapshot["thermal"]["cpu_speed_limit"], 100)

    def test_system_snapshot_text_is_compact(self):
        text = benchmark.system_snapshot_text({
            "ram_used_bytes": 32 * 1024 ** 3,
            "swap_used_bytes": 4 * 1024 ** 3,
            "memory_pressure_level": 2,
            "thermal": {
                "cpu_speed_limit": 80,
                "scheduler_limit": 90,
                "available_cpus": 12,
                "thermal_warning_recorded": True,
                "performance_warning_recorded": False,
            },
        })
        self.assertIn("RAM 32.0 GB", text)
        self.assertIn("Swap 4.0 GB", text)
        self.assertIn("Pressure warning", text)
        self.assertIn("CPU-Limit 80%", text)
        self.assertIn("Scheduler 90%", text)
        self.assertIn("CPUs 12", text)
        self.assertIn("Thermal-Warnung ja", text)
        self.assertIn("Performance-Warnung nein", text)


if __name__ == "__main__":
    unittest.main()
