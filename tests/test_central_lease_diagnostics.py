"""Exercise real process/thread locks, cancellation and bounded diagnostics."""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

import runtime_coordinator as coordinator


def lease(tmp_path, **kwargs):
    return coordinator.runtime_lease(lock_path=tmp_path / "lock", state_dir=tmp_path / "state", **kwargs)


def test_observed_owner_wait_history_and_nested_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator, "POLL_INTERVAL", .005)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def chat():
        try:
            with lease(tmp_path, workload="chat") as evidence:
                assert evidence["observed_holder_role"] == "none"
                entered.set()
                assert release.wait(3)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=chat)
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            with lease(tmp_path, workload="coding", timeout=.03):
                pytest.fail("contending caller entered")
        snapshot = coordinator.lease_state_snapshot(state_dir=tmp_path / "state")
        assert snapshot["active"]["workload"] == "chat"
        assert snapshot["active"]["acquired_at"] > 0
        assert snapshot["waiting_count"] == 0
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert not errors
    with lease(tmp_path, workload="agent") as outer:
        with lease(tmp_path, workload="coding") as inner:
            assert inner is outer
            assert coordinator.lease_state_snapshot(state_dir=tmp_path / "state")["active"]["workload"] == "agent"
    snapshot = coordinator.runtime_state_snapshot(state_dir=tmp_path / "state")
    assert snapshot["active"] is None
    assert snapshot["waits_by_workload"]["coding"]["outcomes"]["timeout"] == 1
    assert snapshot["waits_by_workload"]["chat"]["count"] == 1
    assert all(record["released_at"] >= record["requested_at"] for record in snapshot["recent"])


def test_cross_process_owner_is_observed_and_cancelled_wait_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator, "POLL_INTERVAL", .005)
    code = """
import sys
from pathlib import Path
from runtime_coordinator import runtime_lease
root = Path(sys.argv[1])
with runtime_lease(lock_path=root/'lock', state_dir=root/'state', workload='video'):
    print('ready', flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    cancellation = threading.Event()
    try:
        assert child.stdout.readline().strip() == "ready"
        timer = threading.Timer(.04, cancellation.set)
        timer.start()
        try:
            with pytest.raises(coordinator.CoordinationCancelled):
                with lease(tmp_path, workload="agent", cancel_event=cancellation):
                    pytest.fail("cancelled caller entered")
        finally:
            timer.cancel()
            timer.join()
        # A successful contending call observes the actual external holder.
        seen = threading.Event()
        snapshot = coordinator.lease_state_snapshot

        def observe(**kwargs):
            value = snapshot(**kwargs)
            if value["active"] and value["active"]["workload"] == "video":
                seen.set()
            return value

        monkeypatch.setattr(coordinator, "lease_state_snapshot", observe)

        def release_child():
            seen.wait(2)
            child.stdin.write("done\n")
            child.stdin.flush()

        releaser = threading.Thread(target=release_child)
        releaser.start()
        try:
            with lease(tmp_path, workload="coding", timeout=2) as evidence:
                assert evidence["observed_holder_role"] == "video"
                assert evidence["observed_holder_age_ms"] >= 0
        finally:
            seen.set()
            releaser.join(3)
    finally:
        if child.poll() is None:
            try:
                child.stdin.write("done\n")
                child.stdin.flush()
            except BrokenPipeError:
                # The worker may exit between poll() and the cleanup write.
                pass
        child.wait(timeout=3)
        child.stdin.close()
        child.stdout.close()
    snapshot = coordinator.runtime_state_snapshot(state_dir=tmp_path / "state")
    assert snapshot["active"] is None
    assert snapshot["waiting_count"] == 0
    assert snapshot["waits_by_workload"]["agent"]["outcomes"]["cancelled"] == 1


def test_unknown_workload_errors_and_history_remain_private_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator, "LEASE_HISTORY_LIMIT", 3)
    for _ in range(5):
        with pytest.raises(RuntimeError):
            with lease(tmp_path, workload="secret prompt /Users/private"):
                raise RuntimeError("secret token")
    state = tmp_path / "state"
    (state / "corrupt.json").write_text(json.dumps({"pid": os.getpid(), "updated_at": "invalid"}))
    (state / "nan.json").write_text(json.dumps({"pid": os.getpid(), "updated_at": float("nan")}))
    snapshot = coordinator.runtime_state_snapshot(state_dir=state)
    assert len(snapshot["recent"]) == 3
    assert snapshot["active"] is None
    assert snapshot["waits_by_workload"]["unknown"]["outcomes"]["error"] == 3
    assert "secret" not in json.dumps(snapshot)
    with lease(tmp_path):
        pass


def test_pre_cancelled_nested_request_never_enters(tmp_path):
    event = threading.Event()
    with lease(tmp_path):
        event.set()
        with pytest.raises(coordinator.CoordinationCancelled):
            with lease(tmp_path, cancel_event=event):
                pytest.fail("nested cancelled caller entered")


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf")])
def test_invalid_timeout_does_not_publish_state(tmp_path, timeout):
    with pytest.raises(ValueError):
        with lease(tmp_path, timeout=timeout):
            pass
    assert not (tmp_path / "state").exists()
