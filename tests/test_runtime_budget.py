import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_read_only_memory_cache_reuses_probes_but_admission_stays_fresh(self):
        runtime_coordinator._reset_diagnostic_memory_cache()
        memory = {"total_gb": 48.0, "used_estimate_gb": 10.0,
                  "free_percent": 79.0, "pressure": "normal"}
        with mock.patch.object(
            runtime_coordinator, "memory_budget_snapshot",
            return_value=memory,
        ) as probe, tempfile.TemporaryDirectory() as directory:
            first = runtime_coordinator.runtime_state_snapshot(
                state_dir=Path(directory)
            )["memory"]
            first["pressure"] = "critical"
            second = runtime_coordinator.runtime_state_snapshot(
                state_dir=Path(directory)
            )["memory"]
            self.assertEqual(second["pressure"], "normal")
            self.assertEqual(probe.call_count, 1)

            runtime_coordinator.ensure_model_load_allowed("vision-classifier")
            # Heavy runtime admission must never trust the diagnostic cache.
            self.assertEqual(probe.call_count, 2)

            with runtime_coordinator._DIAGNOSTIC_MEMORY_CONDITION:
                runtime_coordinator._DIAGNOSTIC_MEMORY_AT -= 30.0
            runtime_coordinator.diagnostic_memory_budget_snapshot()
            self.assertEqual(probe.call_count, 3)
        runtime_coordinator._reset_diagnostic_memory_cache()

    def test_simultaneous_diagnostic_calls_share_one_os_probe(self):
        runtime_coordinator._reset_diagnostic_memory_cache()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def probe():
            calls.append(1)
            started.set()
            if not release.wait(5):
                raise TimeoutError("fixture not released")
            return {"pressure": "normal", "headroom_gb": 15.0}

        with mock.patch.object(
            runtime_coordinator, "memory_budget_snapshot", side_effect=probe
        ):
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [
                    pool.submit(runtime_coordinator.diagnostic_memory_budget_snapshot)
                    for _ in range(8)
                ]
                try:
                    self.assertTrue(started.wait(2))
                finally:
                    release.set()
                snapshots = [future.result(timeout=5) for future in futures]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({id(value) for value in snapshots}), 8)
        self.assertTrue(all(value["headroom_gb"] == 15.0 for value in snapshots))
        runtime_coordinator._reset_diagnostic_memory_cache()

    def test_failed_diagnostic_probe_does_not_poison_cache(self):
        runtime_coordinator._reset_diagnostic_memory_cache()
        with mock.patch.object(
            runtime_coordinator, "memory_budget_snapshot",
            side_effect=[
                RuntimeError("probe failed"),
                {"pressure": "normal"},
            ],
        ) as probe:
            with self.assertRaisesRegex(RuntimeError, "probe failed"):
                runtime_coordinator.diagnostic_memory_budget_snapshot()
            self.assertEqual(
                runtime_coordinator.diagnostic_memory_budget_snapshot(),
                {"pressure": "normal"},
            )
            self.assertEqual(probe.call_count, 2)
        runtime_coordinator._reset_diagnostic_memory_cache()

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

    def test_nested_runtime_lease_keeps_outer_workload_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "runtime.lock"
            state_dir = root / "state"

            with runtime_coordinator.runtime_lease(
                lock_path=lock_path,
                state_dir=state_dir,
                workload="video",
            ):
                with runtime_coordinator.runtime_lease(
                    lock_path=lock_path,
                    state_dir=state_dir,
                    workload="chat",
                ):
                    files = list(state_dir.glob("*.json"))
                    self.assertEqual(len(files), 1)
                    payload = json.loads(files[0].read_text(encoding="utf-8"))
                    self.assertEqual(payload["workload"], "video")
                    self.assertEqual(payload["state"], "active")

                self.assertEqual(len(list(state_dir.glob("*.json"))), 1)

            self.assertEqual(list(state_dir.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
