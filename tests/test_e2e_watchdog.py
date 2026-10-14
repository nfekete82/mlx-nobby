"""Regression coverage for bounded release-browser execution."""
import sys

from tests.acceptance.e2e_watchdog import run_e2e, _process_snapshot


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


def test_snapshot_filters_unrelated_process_groups(monkeypatch):
    from types import SimpleNamespace
    import tests.acceptance.e2e_watchdog as watchdog

    def fake_run(*args, **kwargs):
        return SimpleNamespace(stdout=(
            '100 100 1 00:01 99.0 R chrome-headless-shell\n'
            '200 999 1 00:02 50.0 R unrelated-process\n'
            '101 100 100 00:01 0.0 S ffmpeg-mac\n'
        ))

    monkeypatch.setattr(watchdog.subprocess, 'run', fake_run)
    result = _process_snapshot(100)
    assert 'chrome-headless-shell' in result
    assert 'ffmpeg-mac' in result
    assert 'unrelated-process' not in result
