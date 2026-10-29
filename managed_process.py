"""Owned process groups with durable identity and bounded, verified cleanup."""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

import ai_lifecycle_gate as gate

_lock = threading.RLock()
_owned = {}
GUARD = Path(__file__).resolve().parent / "agent/process_guard.py"


class _ManagedPopen(subprocess.Popen):
    def _retire(self):
        path = getattr(self, "_nobby_record_path", None)
        if self.returncode is None or path is None:
            return
        writer = getattr(self, "_nobby_guard_pipe", None)
        if writer:
            writer.close()
        with _lock:
            _owned.pop(self.pid, None)
        path.unlink(missing_ok=True)

    def poll(self):
        result = super().poll()
        self._retire()
        return result

    def wait(self, *args, **kwargs):
        result = super().wait(*args, **kwargs)
        self._retire()
        return result


def identity(pid):
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "lstart=,command="],
                            capture_output=True, text=True, timeout=3)
    return result.stdout.strip() if result.returncode == 0 else None


def _path(pid):
    return gate.ROOT / "processes" / f"{pid}.json"


@gate.admitted
def spawn(command, *, owner=None, **kwargs):
    token = secrets.token_hex(24)
    kwargs.pop("start_new_session", None)
    read_fd, write_fd = os.pipe()
    try:
        process = _ManagedPopen([sys.executable, str(GUARD), token, str(read_fd), *map(str, command)],
                                   pass_fds=(*kwargs.pop("pass_fds", ()), read_fd),
                                   start_new_session=True, **kwargs)
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    writer = None
    try:
        record = {"pid": process.pid, "token": token, "identity": identity(process.pid), "owner": owner}
        if not record["identity"] or token not in record["identity"]:
            raise RuntimeError("Prozessidentität konnte nicht bestätigt werden")
        path = _path(process.pid)
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_suffix(".tmp")
        scratch.write_text(json.dumps(record))
        os.replace(scratch, path)
        process._nobby_record_path = path
        with _lock:
            _owned[process.pid] = (process, record)
        writer = os.fdopen(write_fd, "wb", buffering=0)
        process._nobby_guard_pipe = writer
        writer.write(b"GO\n")
        writer.flush()
        return process
    except BaseException:
        if writer is not None:
            writer.close()
        else:
            os.close(write_fd)
        process.kill()
        process.wait(timeout=5)
        raise


def _matches(record):
    actual = identity(record["pid"])
    return bool(actual and actual == record["identity"] and record["token"] in actual)


def _group_alive(pgid):
    table = subprocess.check_output(["ps", "-axo", "pgid=,stat="], text=True, timeout=3)
    return any(int(row[0]) == pgid and not row[1].startswith("Z")
               for line in table.splitlines() if len(row := line.split()) == 2)


def terminate_record(record, *, term_timeout=10, kill_timeout=5):
    if not _matches(record):
        if identity(record["pid"]) is None and _group_alive(record["pid"]):
            raise RuntimeError(f"Prozessgruppe {record['pid']} existiert ohne verifizierbaren Wächter")
        return  # An exited/reused PID must never receive a signal.
    try:
        os.killpg(record["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + term_timeout
    while (_matches(record) or _group_alive(record["pid"])) and time.monotonic() < deadline:
        with _lock:
            owned = _owned.get(record["pid"])
        if owned:
            owned[0].poll()
        time.sleep(0.05)
    if _matches(record):
        try:
            os.killpg(record["pid"], signal.SIGKILL)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + kill_timeout
    while (_matches(record) or _group_alive(record["pid"])) and time.monotonic() < deadline:
        with _lock:
            owned = _owned.get(record["pid"])
        if owned:
            owned[0].poll()
        time.sleep(0.05)
    if _matches(record) or _group_alive(record["pid"]):
        raise RuntimeError(f"Eigener Prozess {record['pid']} konnte nicht beendet werden")


def terminate(process, **timeouts):
    with _lock:
        owned = _owned.get(process.pid)
    if owned:
        terminate_record(owned[1], **timeouts)
        process.wait(timeout=5)
        forget(process)
    elif process.poll() is None:
        raise RuntimeError("Unregistrierter Prozess wird nicht beendet")


def forget(process):
    if process.poll() is None:
        raise RuntimeError("Laufender Prozess darf nicht deregistriert werden")
    writer = getattr(process, "_nobby_guard_pipe", None)
    if writer:
        writer.close()
    with _lock:
        _owned.pop(process.pid, None)
    getattr(process, "_nobby_record_path", _path(process.pid)).unlink(missing_ok=True)


def stop_all(*, owner=None):
    errors = []
    for path in (gate.ROOT / "processes").glob("*.json"):
        try:
            record = json.loads(path.read_text())
            if owner is not None and record.get("owner") != owner:
                continue
            terminate_record(record)
            with _lock:
                owned = _owned.get(record["pid"])
            if owned:
                owned[0].wait(timeout=5)
                forget(owned[0])
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue  # The owning worker concurrently reaped this process.
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
