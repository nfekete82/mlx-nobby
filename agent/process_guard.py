"""Stdlib-only parent-death guardian; executed in a dedicated process group.

The pipe is kept open by the owning agent/service. EOF (including SIGKILL of
that parent) stops the whole group. No model can start before durable GO.
"""
import os
import selectors
import signal
import subprocess
import sys
import time


def main():
    # argv[1] is an unpredictable ownership token also checked during recovery.
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    control = os.fdopen(int(sys.argv[2]), "rb", buffering=0)
    if control.readline() != b"GO\n" or stopping:
        return 125
    child = subprocess.Popen(sys.argv[3:])
    selector = selectors.DefaultSelector()
    selector.register(control, selectors.EVENT_READ)
    try:
        while child.poll() is None and not stopping:
            if selector.select(0.2) and not os.read(control.fileno(), 256):
                stopping = True
        result = child.poll()
        # Also clean grandchildren after a normally exiting CLI. The guard
        # remains the group leader until cleanup, preventing PGID reuse.
        os.killpg(os.getpgrp(), signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            child.poll()
            try:
                table = subprocess.check_output(["ps", "-axo", "pid=,pgid=,stat="], text=True,
                                                start_new_session=True, timeout=2)
            except (OSError, subprocess.SubprocessError):
                # Verification failure must not leave a model behind after
                # losing its owner. This is our still-owned process group.
                os.killpg(os.getpgrp(), signal.SIGKILL)
                return 137
            alive = [row.split() for row in table.splitlines()]
            if not any(int(row[1]) == os.getpgrp() and int(row[0]) != os.getpid()
                       and not row[2].startswith("Z") for row in alive if len(row) == 3):
                child.wait(timeout=1)
                return result if result is not None else 143
            time.sleep(0.1)
        os.killpg(os.getpgrp(), signal.SIGKILL)
        return 137
    finally:
        selector.close()
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
