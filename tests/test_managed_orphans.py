"""Only children created by these tests may receive signals."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

import ai_lifecycle_gate as gate
import managed_process as managed
import process_identity
import image_providers


def wait_for(check, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.03)
    raise AssertionError("isolated process did not reach expected state")


def sleeper(tmp_path):
    ready = tmp_path / "child.pid"
    code = ("import os,signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(60)")
    process = managed.spawn([sys.executable, "-c", code], owner="image:sdxl", stdout=subprocess.DEVNULL)
    wait_for(ready.exists)
    child = int(ready.read_text())
    wait_for(lambda: any(m["pid"] == child for m in managed._members(managed._owned[process.pid][1])))
    return process, child


def test_dead_guard_live_child_is_verified_and_sigkilled(tmp_path):
    process, child = sleeper(tmp_path)
    path = managed._path(process.pid)
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=3)
    assert path.exists()  # Leader exit must preserve child ownership evidence.
    assert gate.blocked()
    manager=image_providers.SDXLWorkerManager()
    manager._process=process
    assert manager.is_running()  # Health must not report orphaned weights unloaded.
    assert not process_identity.table()[child]["zombie"]
    managed.terminate(process, term_timeout=0.1, kill_timeout=3)
    assert not path.exists()
    assert not path.with_suffix(".members.json").exists()
    assert child not in process_identity.table() or process_identity.table()[child]["zombie"]


def test_concurrent_repeated_cleanup_and_timer_are_idempotent(tmp_path):
    process, child = sleeper(tmp_path)
    errors = []
    def stop():
        try:
            managed.terminate(process, term_timeout=0.1, kill_timeout=3)
        except Exception as exc:
            errors.append(exc)
    timer = threading.Timer(0, stop)
    thread = threading.Thread(target=stop)
    timer.start(); thread.start()
    timer.join(8); thread.join(8)
    assert not timer.is_alive() and not thread.is_alive() and errors == []
    managed.terminate(process)
    assert not managed._path(process.pid).exists()


def test_stale_registry_only_deleted_after_empty_group_verification(tmp_path):
    path = gate.ROOT / "processes/777777.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"pid": 777777, "token": "old", "identity": "old", "owner": None}
    path.write_text(json.dumps(record))
    with mock.patch.object(process_identity, "table", return_value={}):
        managed.stop_all()
    assert not path.exists()
    path.write_text(json.dumps(record))
    unknown = {777778: {"pid": 777778, "ppid": 1, "pgid": 777777, "birth": "other", "zombie": False}}
    with mock.patch.object(process_identity, "table", return_value=unknown), \
         mock.patch.object(managed, "_matches", return_value=False), \
         mock.patch.object(os, "kill") as kill:
        with pytest.raises(RuntimeError):
            managed.terminate_record(record, term_timeout=0, kill_timeout=0)
    assert path.exists() and gate.blocked()
    kill.assert_not_called()


def test_zombies_do_not_keep_gpu_registry_alive():
    record = {"pid": 777777, "token": "old", "identity": "old"}
    zombie = {777777: {"pid": 777777, "pgid": 777777, "birth": "old", "zombie": True}}
    with mock.patch.object(process_identity, "table", return_value=zombie), mock.patch.object(os, "kill") as kill:
        managed.terminate_record(record, term_timeout=0, kill_timeout=0)
    kill.assert_not_called()


def test_birth_reuse_prevents_signalling_recorded_child():
    record = {"pid": 777777, "token": "old", "identity": "old"}
    old = {"pid": 777778, "pgid": 777777, "birth": "1", "zombie": False}
    other = {**old, "birth": "2"}
    with mock.patch.object(managed, "_members", return_value=[old]), \
         mock.patch.object(process_identity, "table", return_value={777778: other}), \
         mock.patch.object(managed, "_matches", return_value=False), mock.patch.object(os, "kill") as kill:
        with pytest.raises(RuntimeError):
            managed.terminate_record(record, term_timeout=0, kill_timeout=0)
    kill.assert_not_called()


def test_sdxl_error_exposes_root_cause_and_preserves_running_reference():
    manager = image_providers.SDXLWorkerManager()
    process = mock.Mock(pid=777777)
    manager._process = process
    with mock.patch.object(image_providers, "terminate_process_tree", side_effect=RuntimeError("unverified children")):
        with pytest.raises(RuntimeError, match="pid=777777.*owner=image:sdxl.*unverified children") as raised:
            manager.close()
    assert raised.value.__cause__ is not None
    assert manager._process is process and gate.blocked()


def test_corrupt_registry_is_preserved_and_blocks_admission():
    path=gate.ROOT/"processes/777777.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("{broken")
    with pytest.raises(ValueError):managed.prune_stale()
    assert gate.blocked() and path.read_text()=="{broken"
