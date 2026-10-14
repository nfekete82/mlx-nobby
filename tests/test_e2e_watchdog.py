"""Regression coverage for bounded release-browser execution."""
import sys

from tests.acceptance.e2e_watchdog import run_e2e


def test_watchdog_passes_through_success_and_logs_output(tmp_path):
    log = tmp_path / 'browser.log'
    result = run_e2e(
        [sys.executable, '-u', '-c', "print('test_example.py::test_ok PASSED')"],
        tmp_path, idle_timeout=2, log_path=log,
    )
    assert result == 0
    assert 'test_ok PASSED' in log.read_text()


def test_watchdog_aborts_stalled_subprocess(tmp_path):
    log = tmp_path / 'browser.log'
    result = run_e2e(
        [sys.executable, '-u', '-c',
         "import time; print('test_example.py::test_hangs', flush=True); time.sleep(30)"],
        tmp_path, idle_timeout=0.3, log_path=log,
    )
    assert result == 124
    content = log.read_text()
    assert 'test_hangs' in content
    assert 'E2E WATCHDOG' in content
