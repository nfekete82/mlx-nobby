"""Isolated regressions for confirmed lifecycle audit failures; never signal live services."""
import io
import json
import signal
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
from unittest import mock

import pytest

import ai_lifecycle_gate as gate
import managed_process
import process_identity
from agent import ai_lifecycle, process_guard


def test_resume_cannot_erase_a_concurrent_shutdown_request(monkeypatch):
    gate.set_blocked(True, "first shutdown")
    pending = gate.ROOT / "shutdown.pending"
    requested = threading.Event()
    touch = type(pending).touch
    def signal_touch(path, *args, **kwargs):
        result = touch(path, *args, **kwargs)
        if threading.current_thread().name == "audit-shutdown" and path == pending:
            requested.set()
        return result
    monkeypatch.setattr(type(pending), "touch", signal_touch)
    errors = []
    def shutdown():
        try:
            gate.set_blocked(True, "concurrent shutdown")
        except BaseException as exc:
            errors.append(exc)
    with gate.barrier():
        thread = threading.Thread(target=shutdown, name="audit-shutdown")
        thread.start()
        assert requested.wait(2)
        try:
            gate.set_blocked(False, "resume")
        except gate.AdmissionClosed:
            pass
        remained_blocked = gate.blocked()
    thread.join(2)
    assert not thread.is_alive() and not errors
    assert remained_blocked, "Resume cleared a pending shutdown before its owner could acquire the barrier"
    assert gate.blocked()


@pytest.mark.parametrize("current_birth,zombie", [("reused", False), ("saved", True)])
def test_service_identity_rejects_reused_pid_and_zombie(current_birth, zombie):
    saved = {"pid": 777777, "birth": "saved", "pgid": 777777, "ppid": 1, "zombie": False}
    current = {**saved, "birth": current_birth, "zombie": zombie}
    record = {"pid": saved["pid"], "identity": "same second and command", "process": saved}
    with mock.patch.object(managed_process, "identity", return_value=record["identity"]), \
         mock.patch.object(process_identity, "snapshot", return_value=current):
        assert not ai_lifecycle._same_process(record)


def test_legacy_service_identity_without_birth_is_never_signalled():
    saved = {"pid": 777777, "identity": "same second and command"}
    current = {"pid": saved["pid"], "birth": "current", "pgid": 777777, "ppid": 1, "zombie": False}
    with mock.patch.object(managed_process, "identity", return_value=saved["identity"]), \
         mock.patch.object(process_identity, "snapshot", return_value=current), \
         mock.patch.object(ai_lifecycle.os, "kill") as kill:
        with pytest.raises(RuntimeError, match="Geburtsidentität"):
            ai_lifecycle._finish_service_processes([saved])
    kill.assert_not_called()


def test_guard_verification_failure_cleans_own_group_and_control_pipe(monkeypatch, tmp_path):
    control = io.BytesIO(b"GO\n")
    monkeypatch.setattr(sys, "argv", ["process_guard.py", "test-token", "123", "mock-model"])
    monkeypatch.setenv("MLX_NOBBY_PROCESS_RECORD", str(tmp_path))
    with mock.patch.object(process_guard.os, "fdopen", return_value=control), \
         mock.patch.object(process_guard.os, "getpid", return_value=777777), \
         mock.patch.object(process_guard.os, "getpgrp", return_value=777777), \
         mock.patch.object(process_guard.os, "getsid", return_value=777777), \
         mock.patch.object(process_guard.subprocess, "Popen"), \
         mock.patch.object(process_guard.identities, "table", side_effect=RuntimeError("snapshot failed")), \
         mock.patch.object(process_guard.os, "killpg") as kill:
        with pytest.raises(RuntimeError, match="snapshot failed"):
            process_guard.main()
    kill.assert_called_with(777777, signal.SIGKILL)
    assert control.closed


def test_remaining_reads_member_evidence_once_without_changing_birth_checks():
    record = {"pid": 777777, "token": "test"}
    old = {"pid": 1, "birth": "old"}
    table = {pid: {"pid": pid, "pgid": 999999, "birth": "current", "zombie": False} for pid in range(1, 101)}
    with mock.patch.object(managed_process, "_members", return_value=[old]) as read:
        assert managed_process.remaining(record, table) == []
    read.assert_called_once_with(record)


def test_admitted_cleanup_failure_does_not_deadlock_waiting_shutdown(monkeypatch):
    gate.set_blocked(True)
    requested = threading.Event()
    original_touch = type(gate.ROOT).touch
    def touch(path, *args, **kwargs):
        value = original_touch(path, *args, **kwargs)
        if threading.current_thread().name == "waiting-shutdown":
            requested.set()
        return value
    monkeypatch.setattr(type(gate.ROOT), "touch", touch)
    with gate.barrier():
        thread = threading.Thread(target=lambda: gate.set_blocked(True), name="waiting-shutdown")
        thread.start()
        assert requested.wait(2)
        gate.set_blocked(True, "admitted worker cleanup failure")
    thread.join(2)
    assert not thread.is_alive() and gate.blocked()


def test_delayed_bootout_is_retried_but_foreign_listener_is_never_killed(monkeypatch):
    probes = []
    def run(command, **kwargs):
        probes.append(command)
        return mock.Mock(returncode=0 if len(probes) == 1 else 113 if command[0] == "launchctl" else 1, stdout=b"")
    with mock.patch.object(ai_lifecycle.subprocess, "run", side_effect=run), \
         mock.patch.object(ai_lifecycle.os, "kill") as kill:
        ai_lifecycle._wait_for_services_stopped()
    assert len(probes) == 1 + 2 * len(ai_lifecycle.SERVICES)
    kill.assert_not_called()


def test_lsof_probe_error_does_not_count_as_a_free_port():
    def run(command, **kwargs):
        return mock.Mock(returncode=113 if command[0] == "launchctl" else 2, stdout=b"")
    with mock.patch.object(ai_lifecycle.subprocess, "run", side_effect=run):
        with pytest.raises(RuntimeError, match="nicht sicher geprüft"):
            ai_lifecycle._wait_for_services_stopped()


def test_launchctl_error_does_not_count_as_a_stopped_service():
    def run(command, **kwargs):
        return mock.Mock(returncode=5 if command[0] == "launchctl" else 1, stdout=b"")
    with mock.patch.object(ai_lifecycle.subprocess, "run", side_effect=run):
        with pytest.raises(RuntimeError, match="LaunchAgent.*nicht sicher geprüft"):
            ai_lifecycle._wait_for_services_stopped()


def _shutdown_proof():
    gate.set_blocked(True, "verified shutdown")
    proof = gate.ROOT / "shutdown-verified.json"
    proof.write_text(json.dumps({"verified_at": time.time(), "gate_state": gate.state()}))
    return proof


def _ready_response():
    return io.BytesIO(json.dumps({"ok": True, "status": "ready", "data": [{"id": "local"}]}).encode())


def test_failed_verify_invalidates_previous_shutdown_proof():
    proof = _shutdown_proof()
    with mock.patch.object(ai_lifecycle, "_wait_for_services_stopped", side_effect=RuntimeError("still loaded")):
        with pytest.raises(RuntimeError, match="still loaded"):
            ai_lifecycle.verify_stopped(mock.Mock())
    assert not proof.exists() and gate.blocked()


def test_readiness_cannot_override_new_lifecycle_epoch():
    proof = _shutdown_proof()
    def response(*args, **kwargs):
        gate.set_blocked(True, "new lifecycle action")
        return _ready_response()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=response):
        with pytest.raises(RuntimeError, match="während der Bereitschaftsprüfung geändert"):
            ai_lifecycle.resume(mock.Mock())
    assert gate.blocked() and not proof.exists()


def test_readiness_rejects_preexisting_proof_from_another_gate_epoch():
    _shutdown_proof()
    gate.set_blocked(True, "new cleanup failure")
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen") as request:
        with pytest.raises(RuntimeError, match="nicht zum aktuellen Lifecycle"):
            ai_lifecycle.resume(mock.Mock())
    request.assert_not_called()
    assert gate.blocked()


def test_resume_consumes_proof_and_is_idempotent_after_verified_success():
    proof = _shutdown_proof()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=lambda *a, **k: _ready_response()):
        assert ai_lifecycle.resume(mock.Mock()) == {"ready": True, "blocked": False}
        assert not proof.exists()
        assert ai_lifecycle.resume(mock.Mock()) == {"ready": True, "blocked": False}
    assert not gate.blocked()


def test_new_ui_action_invalidates_old_proof_before_helper_launch():
    from agent import app as agent
    proof = _shutdown_proof()
    def launch(*args):
        assert not proof.exists() and gate.blocked()
    with mock.patch.object(agent, "_launch_system_lifecycle_helper", side_effect=launch):
        assert agent.system_restart_all()["status"] == "accepted"
    assert not proof.exists()


def test_transient_readiness_503_is_retried_without_releasing_gate():
    _shutdown_proof()
    calls = []
    def response(*args, **kwargs):
        assert gate.blocked()
        calls.append(args[0])
        if len(calls) == 1:
            raise urllib.error.HTTPError(args[0], 503, "loading", {}, io.BytesIO(b"private body"))
        return _ready_response()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=response):
        assert ai_lifecycle.resume(mock.Mock())["ready"]
    assert len(calls) == 1 + len(ai_lifecycle.SERVICES)


@pytest.mark.parametrize("payload", [{"data": "not a model list"}, {"data": [None]}, {"status": [], "data": []}, []])
def test_malformed_readiness_responses_never_open_admission(payload):
    _shutdown_proof()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps(payload).encode())):
        with pytest.raises(RuntimeError):
            ai_lifecycle.resume(mock.Mock())
    assert gate.blocked()


def test_non_json_readiness_does_not_echo_private_response_body():
    _shutdown_proof()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(b'<html>Traceback /Users/private/secret</html>')):
        with pytest.raises(RuntimeError, match="keine gültige JSON-Antwort") as error:
            ai_lifecycle.resume(mock.Mock())
    assert "/Users" not in str(error.value) and gate.blocked()


def test_readiness_timeout_is_bounded(monkeypatch):
    _shutdown_proof()
    monkeypatch.setattr(ai_lifecycle, "READINESS_TIMEOUT_SECONDS", 0)
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")) as request:
        with pytest.raises(RuntimeError, match="Bereitschaftsfrist"):
            ai_lifecycle.resume(mock.Mock())
    request.assert_called_once()
    assert gate.blocked()


def test_legacy_prompt_quotes_cannot_break_executable_ownership_probe():
    table = {pid: {"pid": pid, "ppid": parent, "pgid": pid, "birth": str(pid), "zombie": False}
             for pid, parent in [(10, 1), (11, 10)]}
    cli = str(ai_lifecycle.video_edit_routes.RUNTIME / ".venv/bin/ltx-2-mlx")
    with mock.patch.object(ai_lifecycle, "_launchd_root", side_effect=lambda name: table[10] if name == "agent" else None), \
         mock.patch.object(process_identity, "table", return_value=table), \
         mock.patch.object(process_identity, "snapshot", side_effect=table.__getitem__), \
         mock.patch.object(managed_process, "identity", return_value=f"Thu Oct 29 12:00:00 2026 {cli} --prompt a 'dangling quote"):
        assert [record["pid"] for record in ai_lifecycle._snapshot_service_processes()] == [11]


def test_changed_launchd_root_birth_invalidates_whole_descendant_snapshot():
    root = {"pid": 10, "ppid": 1, "pgid": 10, "birth": "old", "zombie": False}
    with mock.patch.object(ai_lifecycle, "_launchd_root", side_effect=lambda name: root if name == "server" else None), \
         mock.patch.object(process_identity, "table", return_value={10: root}), \
         mock.patch.object(process_identity, "snapshot", return_value={**root, "birth": "reused"}), \
         mock.patch.object(ai_lifecycle.os, "kill") as kill:
        with pytest.raises(RuntimeError, match="Identität"):
            ai_lifecycle._snapshot_service_processes()
    kill.assert_not_called()


def test_agent_restart_restores_durable_failed_lifecycle_state(monkeypatch):
    from agent import app as agent
    initial = {"action": None, "state": "idle", "phase": "idle", "current": 0, "total": 0,
               "message": "", "error": None}
    monkeypatch.setattr(agent, "_SYSTEM_LIFECYCLE_STATE", initial)
    saved = {**initial, "action": "restart-all", "state": "failed", "phase": "readiness",
             "message": "Video nicht bereit", "error": "Video nicht bereit", "updated_at": time.time() - 30}
    gate.set_blocked(True)
    (gate.ROOT / "lifecycle.json").write_text(json.dumps(saved))
    assert agent.system_lifecycle_status() == saved
    assert gate.blocked()


def test_corrupt_durable_lifecycle_is_reported_without_opening_gate(monkeypatch):
    from agent import app as agent
    monkeypatch.setattr(agent, "_SYSTEM_LIFECYCLE_STATE", {"action": None, "state": "idle", "phase": "idle"})
    gate.set_blocked(True)
    (gate.ROOT / "lifecycle.json").write_text("broken")
    state = agent.system_lifecycle_status()
    assert state["state"] == "failed"
    assert "unlesbar" in state["message"] and gate.blocked()


@pytest.mark.parametrize("changes", [{"updated_at": "invalid"}, {"updated_at": float("nan")},
                                     {"message": {"private": "body"}}, {"current": -1}])
def test_invalid_saved_lifecycle_fields_fail_closed(monkeypatch, changes):
    from agent import app as agent
    monkeypatch.setattr(agent, "_SYSTEM_LIFECYCLE_STATE", {"action": None, "state": "idle", "phase": "idle"})
    saved = {"state": "running", "updated_at": time.time(), **changes}
    (gate.ROOT / "lifecycle.json").write_text(json.dumps(saved))
    assert agent.system_lifecycle_status()["state"] == "failed"
    assert gate.blocked()


@pytest.mark.parametrize("payload", [{"state": []}, {"state": "running", "message": {"private": "body"}},
                                     {"state": "running", "error": "x" * 4097}])
def test_lifecycle_progress_rejects_malformed_fields_without_overwriting_status(payload):
    from agent import app as agent
    from fastapi import HTTPException
    before = agent.system_lifecycle_status()
    with pytest.raises(HTTPException) as error:
        agent.system_lifecycle_progress(payload)
    assert error.value.status_code == 422
    assert agent.system_lifecycle_status() == before


def test_guard_refuses_to_spawn_inside_callers_session(monkeypatch, tmp_path):
    control = io.BytesIO(b"GO\n")
    monkeypatch.setattr(sys, "argv", ["process_guard.py", "token", "123", "mock-model"])
    monkeypatch.setenv("MLX_NOBBY_PROCESS_RECORD", str(tmp_path))
    with mock.patch.object(process_guard.os, "fdopen", return_value=control), \
         mock.patch.object(process_guard.os, "getpid", return_value=777777), \
         mock.patch.object(process_guard.os, "getpgrp", return_value=1), \
         mock.patch.object(process_guard.subprocess, "Popen") as spawn, \
         mock.patch.object(process_guard.os, "killpg") as kill:
        with pytest.raises(RuntimeError, match="eigene Sitzung"):
            process_guard.main()
    spawn.assert_not_called()
    kill.assert_not_called()
    assert control.closed


def test_real_guard_scan_failure_does_not_orphan_its_cpu_child(tmp_path):
    pid_file, release = tmp_path / "child.pid", tmp_path / "release"
    read_fd, write_fd = os.pipe()
    child_code = f"import os,time;from pathlib import Path;Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(60)"
    code = f'''
import sys,time
from pathlib import Path
from agent import process_guard as guard
def fail_scan():
    deadline=time.monotonic()+5
    while not Path({str(release)!r}).exists() and time.monotonic()<deadline:
        time.sleep(.01)
    raise RuntimeError("simulated identity scan failure")
guard.identities.table=fail_scan
sys.argv=["guard", "audit-token", {str(read_fd)!r}, sys.executable, "-c", {child_code!r}]
guard.main()
'''
    process = subprocess.Popen([sys.executable, "-c", code], pass_fds=(read_fd,), start_new_session=True,
                               env={**os.environ, "MLX_NOBBY_PROCESS_RECORD": str(tmp_path)},
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    os.close(read_fd)
    child_identity = None
    try:
        os.write(write_fd, b"GO\n")
        deadline = time.monotonic() + 4
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        child_identity = process_identity.snapshot(int(pid_file.read_text()))
        release.touch()
        assert process.wait(timeout=5) == -signal.SIGKILL
        try:
            current = process_identity.snapshot(child_identity["pid"])
        except (ProcessLookupError, FileNotFoundError):
            current = None
        assert current is None or current["zombie"] or not process_identity.same(child_identity, current)
    finally:
        os.close(write_fd)
        release.touch()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)  # Still our unreaped session leader.
            process.wait(timeout=5)
        if child_identity:
            try:
                current = process_identity.snapshot(child_identity["pid"])
                if not current["zombie"] and process_identity.same(child_identity, current):
                    os.kill(current["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.stderr.close()


def test_cross_process_shutdown_intent_cannot_be_cleared_by_resume():
    gate.set_blocked(True)
    pending = gate.ROOT / "shutdown.pending"
    before = pending.stat().st_mtime_ns
    child = None
    try:
        with gate.barrier():
            child = subprocess.Popen([sys.executable, "-c", "import ai_lifecycle_gate as g;g.set_blocked(True,'external test shutdown')"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 3
            while pending.stat().st_mtime_ns == before and time.monotonic() < deadline:
                time.sleep(.01)
            assert pending.stat().st_mtime_ns != before
            with pytest.raises(gate.AdmissionClosed):
                gate.set_blocked(False)
            gate.set_blocked(True, "admitted cleanup failure")
            assert gate.blocked()
        assert child.wait(timeout=5) == 0
        assert gate.blocked()
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stderr.close()
