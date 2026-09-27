import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import runtime_coordinator


class RuntimeBudgetTests(unittest.TestCase):
    def test_memory_budget_snapshot_reports_headroom_and_pressure(self):
        responses = {
            ("sysctl", "-n", "hw.memsize"): str(48 * 1024**3),
            ("memory_pressure",): "System-wide memory free percentage: 25%",
            ("sysctl", "-n", "vm.swapusage"): (
                "total = 4096.00M  used = 1024.00M  free = 3072.00M"
            ),
        }

        def run_text(command, timeout=5):
            return responses.get(tuple(command), "")

        with mock.patch.object(runtime_coordinator, "_run_text", side_effect=run_text):
            snapshot = runtime_coordinator.memory_budget_snapshot()

        self.assertEqual(snapshot["total_gb"], 48.0)
        self.assertEqual(snapshot["available_estimate_gb"], 12.0)
        self.assertEqual(snapshot["used_estimate_gb"], 36.0)
        self.assertEqual(snapshot["reserve_gb"], 6.0)
        self.assertEqual(snapshot["headroom_gb"], 6.0)
        self.assertEqual(snapshot["swap_used_gb"], 1.0)
        self.assertEqual(snapshot["pressure"], "normal")

    def test_memory_budget_snapshot_marks_critical_pressure(self):
        responses = {
            ("sysctl", "-n", "hw.memsize"): str(32 * 1024**3),
            ("memory_pressure",): "System-wide memory free percentage: 7%",
            ("sysctl", "-n", "vm.swapusage"): "total = 0.00M used = 0.00M free = 0.00M",
        }

        with mock.patch.object(
            runtime_coordinator,
            "_run_text",
            side_effect=lambda command, timeout=5: responses.get(tuple(command), ""),
        ):
            snapshot = runtime_coordinator.memory_budget_snapshot()

        self.assertEqual(snapshot["pressure"], "critical")
        self.assertEqual(snapshot["free_percent"], 7.0)

    def test_runtime_lease_publishes_active_workload_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "runtime.lock"
            state_dir = root / "state"

            with runtime_coordinator.runtime_lease(
                lock_path=lock_path,
                state_dir=state_dir,
                workload="video",
            ):
                files = list(state_dir.glob("*.json"))
                self.assertEqual(len(files), 1)
                payload = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["workload"], "video")
                self.assertEqual(payload["state"], "active")

            self.assertEqual(list(state_dir.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
