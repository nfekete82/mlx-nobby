"""Regression: an unverified Admission deployment must never stop services."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ltx-ab-once-safe.py"
spec = importlib.util.spec_from_file_location("ltx_ab_once_safe", SCRIPT)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class GuardedOneShotAdmissionTests(unittest.TestCase):
    def test_missing_admission_module_aborts_without_stopping_services(self):
        with mock.patch.dict(sys.modules, {"ltx_lab.admission": None}), \
             mock.patch.object(lab, "stop_service") as stop, \
             mock.patch.object(lab, "health") as health:
            with self.assertRaisesRegex(RuntimeError, "vollständige lokale Admission"):
                lab.main()
            stop.assert_not_called()
            health.assert_not_called()

    def test_unverified_admission_aborts_before_any_mutation(self):
        fake_gate = mock.Mock()
        fake_verify = mock.Mock(side_effect=RuntimeError("HTTP Error 404"))
        with mock.patch.dict(sys.modules, {
            "ltx_lab.admission": mock.Mock(Gate=lambda: fake_gate),
            "ltx_lab.exclusive": mock.Mock(verify_services=fake_verify),
        }), mock.patch.object(lab, "stop_service") as stop, \
             mock.patch.object(lab, "health") as health:
            with self.assertRaisesRegex(RuntimeError, "Admission-Deployment nicht verifiziert"):
                lab.main()
            fake_verify.assert_called_once_with(fake_gate)
            stop.assert_not_called()
            health.assert_not_called()

    def test_valid_snapshot_still_cannot_start_unfenced_legacy_runner(self):
        fake_verify = mock.Mock(return_value={})
        with mock.patch.dict(sys.modules, {
            "ltx_lab.admission": mock.Mock(Gate=lambda: mock.sentinel.gate),
            "ltx_lab.exclusive": mock.Mock(verify_services=fake_verify),
        }), mock.patch.object(lab, "stop_service") as stop:
            with self.assertRaisesRegex(RuntimeError, "keine durchgängige exklusive"):
                lab.main()
            stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
