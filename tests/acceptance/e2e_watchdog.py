"""Bound an isolated E2E subprocess and retain its last active test on stalls.

Only the subprocess group created here is terminated; local MLX services are untouched.
"""
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def run_e2e(command, cwd, idle_timeout=120, log_path=None):
    log_path = Path(log_path or (Path(cwd) / 'test-results' / 'e2e-watchdog.log'))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True, bufsize=0, env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )
    last_output = time.monotonic()
    recent = bytearray()
    try:
        with log_path.open('wb') as log:
            while True:
                readable, _, _ = select.select([proc.stdout], [], [], 0.5)
                if readable:
                    data = os.read(proc.stdout.fileno(), 4096)
                    if data:
                        last_output = time.monotonic()
                        log.write(data)
                        log.flush()
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                        recent.extend(data)
                        if len(recent) > 16384:
                            del recent[:-16384]
                    elif proc.poll() is not None:
                        break
                elif proc.poll() is not None:
                    # Drain any remaining pipe data on the next iteration.
                    continue
                if proc.poll() is None and time.monotonic() - last_output > idle_timeout:
                    diagnostic = (
                        f'\nE2E WATCHDOG: no test output for {idle_timeout}s; '
                        f'aborting isolated test process group {proc.pid}.\n'
                        f'Last output:\n{recent.decode("utf-8", errors="replace")[-3000:]}\n'
                    )
                    print(diagnostic, file=sys.stderr, flush=True)
                    log.write(diagnostic.encode())
                    return 124
        return proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        proc.stdout.close()
