"""Stdlib-only parent-death guardian; executed in a dedicated process group.

The pipe is kept open by the owning agent/service. EOF (including SIGKILL of
that parent) stops the whole group. No model can start before durable GO.
"""
import json
from pathlib import Path
import os
import selectors
import signal
import subprocess
import sys
import time


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import process_identity as identities


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
    record_root = Path(os.environ.pop("MLX_NOBBY_PROCESS_RECORD"))
    members_path = record_root / f"{os.getpid()}.members.json"
    known = []
    def remember():
        nonlocal known
        rows = identities.table()
        members = {pid: item for pid, item in rows.items() if item["pgid"] == os.getpgrp()
                   or any(identities.same(saved, item) for saved in known)}
        while True:
            added = {pid: item for pid, item in rows.items() if item["ppid"] in members and pid not in members}
            if not added:
                break
            members.update(added)
        values = sorted(members.values(), key=lambda item: item["pid"])
        if values != known:
            temporary = members_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"token": sys.argv[1], "members": values}))
            os.replace(temporary, members_path)
            known = values
    child = None
    selector = None
    try:
        if os.getpgrp() != os.getpid() or os.getsid(0) != os.getpid():
            raise RuntimeError("Prozesswächter benötigt eine eigene Sitzung und Prozessgruppe")
        child = subprocess.Popen(sys.argv[3:])
        remember()
        selector = selectors.DefaultSelector()
        selector.register(control, selectors.EVENT_READ)
        while child.poll() is None and not stopping:
            remember()
            if selector.select(0.2) and not os.read(control.fileno(), 256):
                stopping = True
        remember()
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
    except BaseException:
        # A failed first/periodic identity scan must not orphan the model.
        # spawn() makes us a session/group leader before GO. While that leader
        # is alive the group cannot be reused; never signal a caller's group.
        if child is not None and os.getpgrp() == os.getpid():
            os.killpg(os.getpgrp(), signal.SIGKILL)
        raise
    finally:
        if selector is not None:
            selector.close()
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
