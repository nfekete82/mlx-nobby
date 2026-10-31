"""Owned process groups with durable identity and bounded, verified cleanup."""
import fcntl
from functools import wraps
import logging
from contextlib import contextmanager
import process_identity as identities
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
logger = logging.getLogger(__name__)
GUARD = Path(__file__).resolve().parent / "agent/process_guard.py"


class _ManagedPopen(subprocess.Popen):
    def _retire(self):
        path = getattr(self, "_nobby_record_path", None)
        if self.returncode is None or path is None or not path.exists():
            return
        # poll()/wait() may run concurrently with a cancelling idle timer or
        # another process's lifecycle controller. Never delete evidence just
        # because the leader exited, and never block poll on cleanup's lock.
        with cleanup_lock(path, blocking=False) as acquired:
            if acquired and path.exists():
                record = json.loads(path.read_text())
                if not remaining(record, identities.table()):
                    _remove_record(path, self)
                else:
                    # A dead guardian is not an unloaded model. Outside an
                    # already locked cleanup, stop admission immediately.
                    gate.set_blocked(True, f"Wächter {self.pid} beendet; eigene Kinder/Gruppe noch aktiv")

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


def _startup_identity(process, token, timeout=0.5):
    """Wait briefly for exec to publish argv; the guardian has no GO yet.

    On macOS the first ps can see only ``(python3.11)`` while our freshly
    spawned child is still entering exec. Never accept that incomplete identity
    or launch the workload before the unpredictable ownership token is visible.
    """
    deadline = time.monotonic() + timeout
    while True:
        actual = identity(process.pid)
        if actual and token in actual:
            return actual
        if process.poll() is not None or time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


def _path(pid):
    return gate.ROOT / "processes" / f"{pid}.json"


def is_active(process):
    if process.poll() is None:
        return True
    path = getattr(process, "_nobby_record_path", None)
    if path is None:
        return False
    try:
        return bool(remaining(json.loads(path.read_text()), identities.table()))
    except FileNotFoundError:
        return False
    except Exception:
        gate.set_blocked(True, f"Prozessstatus {process.pid} nicht verifizierbar")
        return True


@gate.admitted
def spawn(command, *, owner=None, **kwargs):
    token = secrets.token_hex(24)
    kwargs.pop("start_new_session", None)
    read_fd, write_fd = os.pipe()
    environment = dict(kwargs.pop("env", os.environ))
    try:
        process = _ManagedPopen([sys.executable, str(GUARD), token, str(read_fd), *map(str, command)],
                                   pass_fds=(*kwargs.pop("pass_fds", ()), read_fd),
                                   start_new_session=True, env={**environment, "MLX_NOBBY_PROCESS_RECORD": str(gate.ROOT / "processes")}, **kwargs)
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    writer = None
    try:
        record = {"pid": process.pid, "token": token, "identity": _startup_identity(process, token), "owner": owner or "nobby:subprocess",
                  "leader": identities.table().get(process.pid), "state": "registered"}
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
        # GO may have reached the guardian before a pipe/write error. The
        # unreaped group leader is still our own child: include its model.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        raise


def _matches(record):
    actual = identity(record["pid"])
    return bool(actual and actual == record["identity"] and record["token"] in actual)


def _group_alive(pgid):
    table = subprocess.check_output(["ps", "-axo", "pgid=,stat="], text=True, timeout=3)
    return any(int(row[0]) == pgid and not row[1].startswith("Z")
               for line in table.splitlines() if len(row := line.split()) == 2)


@contextmanager
def cleanup_lock(path, *, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".cleanup.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _members(record):
    path = _path(record["pid"]).with_suffix(".members.json")
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    if value.get("token") != record["token"]:
        raise RuntimeError("Prozess-Kindregistrierung hat ungültiges Eigentum")
    return value.get("members", [])


def remaining(record, table):
    return [value for value in table.values() if not value["zombie"] and (
        value["pgid"] == record["pid"] or any(identities.same(saved, value) for saved in _members(record)))]


def _remove_record(path, process=None):
    if process is None:
        with _lock:
            owned = _owned.get(int(path.stem))
        if owned:
            process = owned[0]
            subprocess.Popen.poll(process)
    if process is not None:
        writer = getattr(process, "_nobby_guard_pipe", None)
        if writer:
            writer.close()
        with _lock:
            _owned.pop(process.pid, None)
    path.unlink(missing_ok=True)
    path.with_suffix(".members.json").unlink(missing_ok=True)


def prune_stale():
    try:
        return _prune_stale()
    except Exception:
        gate.set_blocked(True, "Prozessregistrierungen konnten nicht sicher geprüft werden")
        logger.exception("process_registry_verification_failed")
        raise


def _prune_stale():
    """Read-only verification, then remove only definitively empty records."""
    removed = []
    for path in (gate.ROOT / "processes").glob("*.json"):
        if not path.stem.isdigit():
            continue
        with cleanup_lock(path, blocking=False) as acquired:
            if not acquired or not path.exists():
                continue
            record = json.loads(path.read_text())
            if not remaining(record, identities.table()):
                _remove_record(path)
                removed.append(record["pid"])
    return removed


def verified_cleanup(function):
    @wraps(function)
    def wrapper(record, **kwargs):
        try:
            return function(record, **kwargs)
        except Exception:
            gate.set_blocked(True, f"Prozessbereinigung nicht verifiziert: pid={record.get('pid')} owner={record.get('owner')}")
            logger.exception("process_cleanup_failed pid=%s pgid=%s owner=%s",
                             record.get("pid"), record.get("pid"), record.get("owner"))
            raise
    return wrapper


@verified_cleanup
def terminate_record(record, *, term_timeout=10, kill_timeout=5):
    path = _path(record["pid"])
    with cleanup_lock(path):
        initial = identities.table()
        known = _members(record)
        leader = record.get("leader")
        if leader and identities.same(leader, initial.get(record["pid"])):
            # A live group leader proves ownership of group membership now.
            known += [item for item in initial.values() if item["pgid"] == record["pid"]]
        elif not leader and _matches(record):
            # Adopt an old, still-live token-verified Nobby guardian safely.
            known += [item for item in initial.values() if item["pgid"] == record["pid"]]
        initial_safe = [{k: item[k] for k in ("pid", "pgid", "zombie")} for item in remaining(record, initial)]
        for sig, grace, phase in ((signal.SIGTERM, term_timeout, "sigterm"),
                                  (signal.SIGKILL, kill_timeout, "sigkill")):
            if path.exists():
                record.update(state="stopping", cleanup_phase=phase, updated_at=time.time())
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(record))
                os.replace(temporary, path)
            current = identities.table()
            live = remaining(record, current)
            logger.info("process_cleanup pid=%s pgid=%s owner=%s phase=%s initial=%s remaining=%s",
                        record["pid"], record["pid"], record.get("owner"), phase, initial_safe,
                        [{k: item[k] for k in ("pid", "pgid", "zombie")} for item in live])
            # Individual birth-verified signals still work after the guardian
            # has exited. Unknown group members fail closed, never get killed.
            unknown = [item["pid"] for item in live if not any(identities.same(saved, item) for saved in known)]
            for item in live:
                if item["pid"] in unknown:
                    continue
                try:
                    if identities.same(item, identities.table().get(item["pid"])):
                        os.kill(item["pid"], sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                with _lock:
                    owned = _owned.get(record["pid"])
                if owned:
                    subprocess.Popen.poll(owned[0])  # Reap without recursive retirement.
                if not remaining(record, identities.table()):
                    return
                time.sleep(0.05)
        final = remaining(record, identities.table())
        if final:
            error = (f"Prozessbereinigung nicht verifiziert: pid={record['pid']} pgid={record['pid']} "
                     f"owner={record.get('owner')} phase=verification-after-sigkill initial={initial_safe} remaining="
                     + str([{k: item[k] for k in ("pid", "pgid", "zombie")} for item in final]))
            gate.set_blocked(True, error)
            raise RuntimeError(error)


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
    path = getattr(process, "_nobby_record_path", _path(process.pid))
    with cleanup_lock(path):
        if path.exists() and remaining(json.loads(path.read_text()), identities.table()):
            raise RuntimeError(f"Prozessgruppe {process.pid} ist noch aktiv")
        _remove_record(path, process)


def stop_all(*, owner=None):
    errors = []
    for path in (gate.ROOT / "processes").glob("*.json"):
        if not path.stem.isdigit():
            continue
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
            with cleanup_lock(path):
                if not remaining(record, identities.table()):
                    _remove_record(path)
        except FileNotFoundError:
            continue  # The owning worker concurrently reaped this process.
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{path.name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
