"""CPU-only lifecycle tests. Only subprocesses created here receive signals."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import ai_lifecycle_gate as gate
import managed_process as processes
from agent import video_edit_routes as edit
from agent import ai_lifecycle


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("Isolated test process did not reach expected state")


def test_admission_race_and_durable_failure_barrier():
    entered, leave, closed = threading.Event(), threading.Event(), threading.Event()
    @gate.admitted
    def register():
        entered.set()
        assert leave.wait(3)
    worker = threading.Thread(target=register)
    shutdown = threading.Thread(target=lambda: (gate.set_blocked(True), closed.set()))
    worker.start()
    assert entered.wait(3)
    shutdown.start()
    assert not closed.wait(0.05)
    leave.set()
    worker.join(3)
    shutdown.join(3)
    assert closed.is_set() and gate.blocked()
    with pytest.raises(gate.AdmissionClosed):
        register()
    gate.set_blocked(False, "verified restart")
    gate.check()


def test_corrupt_gate_fails_closed():
    gate.ROOT.mkdir(parents=True, exist_ok=True)
    (gate.ROOT / "gate.json").write_text("broken")
    assert gate.blocked()


def test_native_inference_rejected_but_health_and_cancel_remain_reachable():
    app = FastAPI()
    app.add_middleware(gate.AIAdmissionGuard)
    app.post("/jobs")(lambda: {"accepted": True})
    app.post("/jobs/test/cancel")(lambda: {"cancel_requested": True})
    app.get("/health")(lambda: {"ok": True})
    client = TestClient(app)
    gate.set_blocked(True)
    assert client.post("/jobs").status_code == 503
    assert client.post("/jobs/test/cancel").status_code == 200
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("description", ["Denoising", "Denoising (guided)", "Denoising (res2s)"])
def test_real_ltx018_tqdm_phase_counts(description):
    fields = edit.parse_progress(f"{description}:  25%|██▌       | 2/8 [00:12<00:36, 6.0s/it]")
    assert fields["current_step"] == 2 and fields["total_steps"] == 8
    assert fields["phase_progress"] == 0.25
    assert fields["progress"] is None and fields["progress_scope"] == "phase"


@pytest.mark.parametrize("line,phase", [
    ("[Loading text encoder (Gemma)] ...", "loading"),
    ("[Encoding prompt] ...", "encoding_prompt"),
    ("[Decoding video + audio + muxing] ...", "decoding"),
])
def test_real_ltx018_bracketed_phase_markers(line, phase):
    fields = edit.parse_progress(line)
    assert fields["phase"] == phase and fields["phase_progress"] is None


def test_carriage_returns_partial_records_unknown_output_and_bounded_tail(tmp_path):
    log = tmp_path / "ltx.log"
    log.write_bytes(b"Loading model\nDenoising: 0%| | 0/8 [00:00]\rDenoising: 25%| | 2/")
    tail = edit.ProgressTail(log)
    fields = tail.read()
    assert fields["current_step"] == 0
    with log.open("ab") as stream:
        stream.write(b"8 [00:10]\r")
    assert tail.read()["current_step"] == 2
    with log.open("ab") as stream:
        stream.write(b"opaque model work\n" + b"x" * 200000)
    fields = tail.read()
    assert set(fields) == {"last_activity_at"}
    assert len(tail.pending) <= 8192
    assert edit.parse_progress("LTX processing") == {}
    assert edit.parse_progress("Denoising: 100%| | 9/8 [00:10]") == {}


def test_process_group_cancel_kills_grandchild_and_preserves_other_process(tmp_path):
    child_pid = tmp_path / "child.pid"
    code = ("import subprocess,sys,time; from pathlib import Path; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            f"Path({str(child_pid)!r}).write_text(str(p.pid)); time.sleep(60)")
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    process = processes.spawn([sys.executable, "-c", code], stdout=subprocess.DEVNULL)
    try:
        wait_for(child_pid.exists)
        pid = int(child_pid.read_text())
        processes.terminate(process, term_timeout=2)
        assert process.poll() is not None
        wait_for(lambda: processes.identity(pid) is None)
        assert sentinel.poll() is None
        processes.terminate(process)  # Idempotent after deregistration.
    finally:
        if process.poll() is None:
            processes.terminate(process)
        sentinel.terminate()
        sentinel.wait(timeout=3)


def test_sigkill_escalation_for_uncooperative_owned_group(tmp_path):
    ready = tmp_path / "ready"
    code = ("import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            f"Path({str(ready)!r}).touch(); time.sleep(60)")
    process = processes.spawn([sys.executable, "-c", code], stdout=subprocess.DEVNULL)
    try:
        wait_for(ready.exists)
        processes.terminate(process, term_timeout=0.2, kill_timeout=3)
        assert process.returncode == -signal.SIGKILL
    finally:
        if process.poll() is None:
            processes.terminate(process)


def test_parent_pipe_eof_stops_owned_cli(tmp_path):
    ready = tmp_path / "ready"
    process = processes.spawn([sys.executable, "-c",
                               f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(60)"],
                              stdout=subprocess.DEVNULL)
    try:
        wait_for(ready.exists)
        process._nobby_guard_pipe.close()
        process.wait(timeout=5)
        processes.forget(process)
    finally:
        if process.poll() is None:
            processes.terminate(process)


def test_stale_pid_identity_never_receives_signal():
    record = {"pid": os.getpid(), "token": "not-our-process", "identity": "stale identity"}
    with mock.patch.object(processes.os, "killpg") as kill:
        processes.terminate_record(record)
    kill.assert_not_called()


def test_cancelled_preparation_releases_lock_and_preserves_source(tmp_path, monkeypatch):
    job_id = "f" * 24
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    output = tmp_path / "partial.mp4"
    output.write_bytes(b"partial")
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(edit, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(edit, "_jobs", {job_id: {"id": job_id, "status": "queued", "_cancel_event": cancel}})
    monkeypatch.setattr(edit, "_generation_lock", threading.Lock())
    monkeypatch.setattr(edit.runtime_coordinator, "video_runtime", lambda *a, **kw: nullcontext())
    edit._generation_lock.acquire()
    edit._run(job_id, mock.Mock(), source, {}, [], output)
    assert edit._jobs[job_id]["status"] == "cancelled"
    assert not output.exists() and source.read_bytes() == b"original"
    assert not edit._generation_lock.locked()


def test_reload_recovery_is_persistent_and_keeps_completed_media(tmp_path, monkeypatch):
    monkeypatch.setattr(edit, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(edit, "OUTPUT", tmp_path / "videos")
    monkeypatch.setattr(edit, "_jobs", {})
    edit.JOB_DIR.mkdir()
    edit.OUTPUT.mkdir()
    for job_id, status in (("a"*24, "generating"), ("b"*24, "completed")):
        (edit.JOB_DIR / f"{job_id}.json").write_text(json.dumps({"id": job_id, "status": status}))
        (edit.OUTPUT / f"{job_id}.mp4").write_bytes(b"video")
    edit.recover_jobs()
    assert edit._jobs["a"*24]["status"] == "failed"
    assert json.loads((edit.JOB_DIR / ("a"*24 + ".json")).read_text())["status"] == "failed"
    assert not (edit.OUTPUT / ("a"*24 + ".mp4")).exists()
    assert (edit.OUTPUT / ("b"*24 + ".mp4")).read_bytes() == b"video"


def test_failed_readiness_keeps_admission_closed(monkeypatch):
    gate.set_blocked(True)
    (gate.ROOT / "shutdown-verified.json").write_text("{}")
    agent = mock.Mock()
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=OSError("offline")):
        with pytest.raises(OSError):
            ai_lifecycle.resume(agent)
    assert gate.blocked()


def test_successful_readiness_reopens_admission():
    import io
    gate.set_blocked(True)
    (gate.ROOT / "shutdown-verified.json").write_text("{}")
    def response(url, **kwargs):
        return io.BytesIO(json.dumps({"data": [{"id": "local"}], "ok": True, "status": "ready"}).encode())
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen", side_effect=response) as probe:
        assert ai_lifecycle.resume(mock.Mock())["ready"]
    assert probe.call_count == 7 and not gate.blocked()


def test_resume_without_verified_shutdown_is_rejected():
    gate.set_blocked(True)
    with mock.patch.object(ai_lifecycle.urllib.request, "urlopen") as probe:
        with pytest.raises(RuntimeError, match="noch nicht verifiziert"):
            ai_lifecycle.resume(mock.Mock())
    probe.assert_not_called()
    assert gate.blocked()


def test_empty_shutdown_verified_and_foreign_listener_is_never_killed(monkeypatch):
    from agent import app as agent
    monkeypatch.setattr(edit, "_jobs", {})
    monkeypatch.setattr(edit, "_generation_lock", threading.Lock())
    monkeypatch.setattr(ai_lifecycle.media_queue, "_jobs", {})
    monkeypatch.setattr(ai_lifecycle.talking_photo, "JOBS", gate.ROOT / "no-jobs")
    with mock.patch.object(ai_lifecycle.subprocess, "run", return_value=mock.Mock(returncode=1, stdout=b"")):
        assert ai_lifecycle.verify_stopped(agent)["verified"]
    assert (gate.ROOT / "shutdown-verified.json").exists()
    (gate.ROOT / "shutdown-verified.json").unlink()
    def run(command, **kwargs):
        return mock.Mock(returncode=1, stdout=b"12345" if command[0] == "lsof" else b"")
    with mock.patch.object(ai_lifecycle.subprocess, "run", side_effect=run), \
         mock.patch.object(ai_lifecycle.os, "kill") as kill:
        with pytest.raises(RuntimeError, match="weiterhin belegt"):
            ai_lifecycle.verify_stopped(agent)
    kill.assert_not_called()
    assert not (gate.ROOT / "shutdown-verified.json").exists()


def test_migration_snapshot_requires_agent_ancestry_and_executable_path(monkeypatch):
    cli = str(edit.RUNTIME / ".venv/bin/ltx-2-mlx")
    values = {10: "Thu Oct 29 12:00:00 2026 python agent", 11: "Thu Oct 29 12:00:00 2026 " + cli + " extend",
              12: "Thu Oct 29 12:00:00 2026 ffmpeg child", 21: "Thu Oct 29 12:00:00 2026 " + cli + " extend",
              13: "Thu Oct 29 12:00:00 2026 echo " + cli}
    def run(command, **kwargs):
        if command[-1].endswith("mlx-agent"):
            return mock.Mock(returncode=0, stdout="  pid = 10\n")
        return mock.Mock(returncode=1, stdout="")
    with mock.patch.object(ai_lifecycle.subprocess, "run", side_effect=run), \
         mock.patch.object(ai_lifecycle.subprocess, "check_output", return_value="10 1\n11 10\n12 11\n13 10\n21 1\n"), \
         mock.patch.object(processes, "identity", side_effect=values.get):
        records = ai_lifecycle._snapshot_service_processes()
    assert {record["pid"] for record in records} == {11, 12}


def test_duplicate_http_shutdown_launches_once_and_stale_state_can_recover():
    from agent import app as agent
    with mock.patch.object(agent, "_launch_system_lifecycle_helper") as launch:
        agent.system_shutdown_ai()
        agent.system_shutdown_ai()
        launch.assert_called_once()
        agent._SYSTEM_LIFECYCLE_STATE["updated_at"] = time.time() - 30
        assert agent.system_restart_all()["action"] == "restart-all"
        assert launch.call_count == 2


def test_cancelled_batch_cannot_be_resurrected_by_late_completion(tmp_path, monkeypatch):
    from agent import app as agent
    monkeypatch.setattr(agent, "BATCH_DIRECTORY", tmp_path)
    monkeypatch.setattr(agent, "BATCH_JOBS_FILE", tmp_path / "batch.json")
    agent.save_batch_jobs({"job": {"id": "job", "status": "cancelled"}})
    agent.save_batch_jobs({"job": {"id": "job", "status": "completed", "result": "late"}})
    assert agent.load_batch_jobs()["job"]["status"] == "cancelled"


@pytest.mark.parametrize("mode", ["progress", "silent_cancel", "double_cancel"])
def test_edit_worker_real_cpu_progress_and_nonblocking_cancel(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(edit, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(edit, "OUTPUT", tmp_path / "out")
    monkeypatch.setattr(edit, "RUNTIME", tmp_path)
    monkeypatch.setattr(edit, "_jobs", {})
    monkeypatch.setattr(edit, "_generation_lock", threading.Lock())
    monkeypatch.setattr(edit, "_runtime_ready", lambda: True)
    monkeypatch.setattr(edit, "_video_idle", lambda: None)
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(edit, "source_path", lambda *a: source)
    monkeypatch.setattr(edit, "probe", lambda *a: {"fps": 24})
    monkeypatch.setattr(edit.runtime_coordinator, "video_runtime", lambda *a, **k: nullcontext())
    monkeypatch.setattr(edit.media_lifecycle, "register", mock.Mock())
    def command(request, source, destination, info):
        code = "import time,sys; from pathlib import Path; "
        if mode == "progress":
            code += "Path(sys.argv[sys.argv.index('--output')+1]).write_bytes(b'partial'); "
            code += "print('Denoising: 25%| | 2/8 [00:10]', flush=True); time.sleep(1); "
            code += "Path(sys.argv[sys.argv.index('--output')+1]).write_bytes(b'\\0\\0\\0\\x18ftyp' + b'valid' * 20)"
        else:
            code += "time.sleep(60)"  # No stdout; cancellation must still work.
        return [sys.executable, "-u", "-c", code, "--output", str(destination)]
    monkeypatch.setattr(edit, "build_command", command)
    app = FastAPI()
    edit.install_routes(app)
    client = TestClient(app)
    request = {"source_kind": "video", "source_id": "a"*24, "operation": "extend", "prompt": "Continue motion"}
    job = client.post("/api/video/edit/jobs", json=request).json()
    job_id = job["id"]
    status = lambda: client.get("/api/video/edit/jobs/" + job_id).json()
    try:
        wait_for(lambda: status()["status"] == "generating")
        assert client.get("/api/video/edit/jobs").json()["jobs"][0]["id"] == job_id
        assert client.post("/api/video/edit/jobs", json=request).status_code == 409
        if mode == "progress":
            wait_for(lambda: status().get("current_step") == 2)
            assert status()["progress"] is None
            from agent import media_library_routes as library
            with mock.patch.object(library.media_lifecycle, "_root_for", return_value=edit.OUTPUT):
                assert library.list_assets("video")["assets"] == []
            wait_for(lambda: status()["status"] == "completed")
            assert status()["progress"] == 1
            assert (edit.OUTPUT / f"{job_id}.mp4").is_file()
            assert not list(edit.OUTPUT.glob("*.partial.mp4"))
        else:
            before = time.monotonic()
            response = client.post(f"/api/video/edit/jobs/{job_id}/cancel")
            assert response.json()["status"] in {"cancelling", "cancelled"}
            if mode == "double_cancel":
                assert client.post(f"/api/video/edit/jobs/{job_id}/cancel").status_code == 200
            wait_for(lambda: status()["status"] == "cancelled")
            assert time.monotonic() - before < 5
            assert not (edit.OUTPUT / f"{job_id}.mp4").exists()
        assert source.read_bytes() == b"original"
        wait_for(lambda: not edit._generation_lock.locked())
        assert client.get("/api/video/edit/jobs").json()["jobs"] == []
    finally:
        edit.cancel_all()
        processes.stop_all()
        wait_for(lambda: not edit._generation_lock.locked())


def test_central_shutdown_reuses_existing_cancellation_registries(monkeypatch):
    from agent import app as agent
    monkeypatch.setattr(ai_lifecycle, "_snapshot_service_processes", lambda: [])
    monkeypatch.setattr(edit, "_jobs", {})
    monkeypatch.setattr(ai_lifecycle.media_queue, "_ensure_loaded_locked", lambda: None)
    monkeypatch.setattr(ai_lifecycle.media_queue, "_jobs", {
        "a"*24: {"id": "a"*24, "kind": "video", "status": "queued"},
        "b"*24: {"id": "b"*24, "kind": "image", "status": "queued"},
    })
    monkeypatch.setattr(ai_lifecycle.shorts_jobs, "_load_jobs", lambda: {"short": {"id": "short", "status": "running"}})
    monkeypatch.setattr(ai_lifecycle.talking_photo, "JOBS", gate.ROOT / "no-talking-jobs")
    monkeypatch.setattr(agent, "load_batch_jobs", lambda: {})
    monkeypatch.setattr(agent, "save_batch_jobs", lambda j: None)
    with mock.patch.object(ai_lifecycle.media_queue, "cancel") as media_cancel, \
         mock.patch.object(ai_lifecycle.shorts_jobs, "cancel_short_job") as short_cancel, \
         mock.patch.object(ai_lifecycle.run_state, "cancel_all") as run_cancel:
        assert ai_lifecycle.quiesce(agent)["quiesced"]
        assert ai_lifecycle.quiesce(agent)["quiesced"]  # Repeated shutdown.
    assert media_cancel.call_count == 4 and short_cancel.call_count == 2
    assert run_cancel.call_count == 2 and gate.blocked()


@pytest.mark.parametrize("failure", [False, True])
def test_terminal_stop_ai_and_restart_all_execute_central_protocol(tmp_path, failure):
    # Load only function definitions; replace every service operation with a
    # test adapter. Never execute the manager's production command dispatch.
    source = Path("scripts/mlx").read_text().rsplit('\ncase "$1" in\n', 1)[0]
    harness = source + '''
ai_lifecycle() { echo "central $1"; if [ "$1" = "verify-stopped" ] && [ "$FAIL_VERIFY" = "1" ]; then return 1; fi; }
mlx_service_stop() { echo "stop $1"; }
restart() { echo "start server"; }
mlx_service_ensure_running() { echo "start $1"; }
mlx_service_restart() { echo "start $1"; }
mlx_service_wait_ready() { return 0; }
services_status() { :; }
restart_all
'''
    result = subprocess.run(["bash"], input=harness, text=True, capture_output=True,
                            env={**os.environ, "FAIL_VERIFY": "1" if failure else "0"}, timeout=5)
    assert "central quiesce" in result.stdout
    assert "central verify-stopped" in result.stdout
    if failure:
        assert result.returncode != 0
        assert "start server" not in result.stdout
        assert "central resume" not in result.stdout
    else:
        assert result.returncode == 0
        assert result.stdout.index("central verify-stopped") < result.stdout.index("start server")
        assert "central resume" in result.stdout


def test_failed_process_cleanup_is_visible_and_blocks_new_jobs(tmp_path, monkeypatch):
    job_id = "c"*24
    monkeypatch.setattr(edit, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(edit, "_jobs", {job_id: {"id": job_id, "status": "generating"}})
    with mock.patch.object(processes, "terminate", side_effect=RuntimeError("identity unavailable")):
        assert not edit._ensure_terminated(job_id, mock.Mock())
    job = edit._jobs[job_id]
    assert job["status"] == "failed" and job["cleanup_failed"]
    assert "identity unavailable" in job["error"] and gate.blocked()
