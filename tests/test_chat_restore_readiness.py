"""Execute production Bash polling with fake API/clock; never load a model."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import runpy
import subprocess
import threading

import pytest
import runtime_coordinator as rc

ROOT = Path(__file__).resolve().parents[1]
extract = runpy.run_path(str(ROOT / 'scripts/benchmark-chat-readiness.py'))['function']


def run_wait(api, *, timeout=3):
    source = (ROOT / 'scripts/mlx').read_text()
    script = extract(source, 'wait_for_api')
    # Drive Bash's own SECONDS counter instead of using real sleeps. Failed
    # probes advance one second; sleep merely verifies the requested cadence.
    script += '''
count=0
sleep() { [ "$1" = 0.2 ] || exit 22; }
'''
    script += api + f'\nwait_for_api {timeout}\nresult=$?\necho "result=$result probes=$count"\nexit "$result"\n'
    return subprocess.run(['/bin/bash', '-c', script], capture_output=True,
                          text=True, timeout=5)


@pytest.mark.parametrize('ready_after', [1, 2, 3])
def test_wait_returns_only_after_successful_api_probe(ready_after):
    result = run_wait(f'''api_ready() {{
        count=$((count + 1))
        if [ "$count" -ge {ready_after} ]; then return 0; fi
        SECONDS=$((SECONDS + 1))
        return 1
    }}''')
    assert result.returncode == 0
    assert f'result=0 probes={ready_after}' in result.stdout


def test_failed_start_times_out_and_returns_failure():
    result = run_wait('''api_ready() {
        count=$((count + 1))
        SECONDS=$((SECONDS + 1))
        return 1
    }''')
    assert result.returncode == 1
    assert 'result=1 probes=3' in result.stdout
    assert 'noch nicht bereit' in result.stdout


def test_slow_health_probe_counts_towards_start_timeout():
    result = run_wait('''api_ready() {
        count=$((count + 1))
        SECONDS=$((SECONDS + 4))
        return 1
    }''')
    assert result.returncode == 1
    assert 'result=1 probes=1' in result.stdout


def test_zero_timeout_never_reports_success():
    result = run_wait('api_ready() { count=$((count + 1)); return 0; }', timeout=0)
    assert result.returncode == 1
    assert 'result=1 probes=0' in result.stdout


@pytest.mark.parametrize('outcome', ['success', 'cancel', 'failure'])
def test_restore_keeps_real_runtime_lease_until_start_returns(tmp_path, monkeypatch, outcome):
    """A second heavy job cannot enter while start waits, even after cancel."""
    restoring = threading.Event()
    finish_restore = threading.Event()
    cancelled = threading.Event()
    commands = []
    lock_path = tmp_path / 'runtime.lock'
    safe = dict(total_gb=48, used_estimate_gb=12, free_percent=75,
                headroom_gb=30, pressure='normal')
    monkeypatch.setattr(rc, 'wait_for_idle', lambda *a, **kw: None)
    monkeypatch.setattr(rc, 'release_idle_speech_runtime', lambda *a, **kw: {})
    monkeypatch.setattr(rc, 'release_idle_musetalk_runtime', lambda *a, **kw: {})

    def command(action):
        commands.append(action)
        if action == 'start':
            restoring.set()
            assert finish_restore.wait(3)
            if outcome == 'failure':
                raise RuntimeError('fixture start failed')

    def image_job():
        with rc.image_runtime(
            cancelled, lock_path=lock_path, chat_loaded=lambda: True,
            chat_command=command, memory_snapshot=lambda: safe,
            exclusive_models=True,
        ):
            pass

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(image_job)
        try:
            assert restoring.wait(2)
            if outcome == 'cancel':
                cancelled.set()
            with pytest.raises(TimeoutError):
                with rc.runtime_lease(lock_path=lock_path, workload='video', timeout=.03):
                    pytest.fail('Second workload entered during chat restoration')
        finally:
            finish_restore.set()
        if outcome == 'failure':
            with pytest.raises(RuntimeError, match='fixture start failed'):
                future.result(timeout=3)
        else:
            future.result(timeout=3)
    assert commands == ['stop', 'start']
    with rc.runtime_lease(lock_path=lock_path, timeout=.1):
        pass
