"""Bounded 4B-supervisor contracts; no real models, SQLite or media dispatch."""
import time
from pathlib import Path
from unittest import mock

import pytest

from agent import memory_model_coordination as ctl
from agent import memory_model_supervisor as sup


@pytest.fixture(autouse=True)
def isolated_control(tmp_path, monkeypatch):
    for name, path in {
        "ROOT": tmp_path,
        "STATE": tmp_path / "state.json",
        "DEMAND": tmp_path / "media-demand.json",
        "LOCK": tmp_path / "inference.lock",
        "MEDIA_JOB_FILE": tmp_path / "jobs.json",
    }.items():
        monkeypatch.setattr(ctl, name, path)
    monkeypatch.setattr(sup.rc, "model_load_reserve_gb",
                        lambda kind: {"video": 20, "image": 18}[kind])
    monkeypatch.setattr(sup.rc, "projected_memory_hard_limit_reached",
                        lambda data, reserve: 100 - data["free_percent"] + reserve / 48 * 100 >= 90)
    monkeypatch.setattr(sup.rc, "memory_relief_needed",
                        lambda data, min_headroom_gb=4: data["headroom_gb"] < min_headroom_gb)


def test_memory_admission_and_media_priority():
    safe = {"free_percent": 50, "headroom_gb": 20, "pressure": "normal"}
    assert sup.should_load(safe)
    assert not sup.should_unload(safe, "image")
    assert sup.should_unload(safe, "video")
    assert not sup.should_load({"free_percent": 10, "headroom_gb": 0})


def test_media_markers_expire_but_running_jobs_hold_priority():
    ctl.note_media_demand("video")
    assert ctl.active_media_kind() == "video"
    ctl._write(ctl.DEMAND, {"kind": "video", "until": time.time() - 1})
    assert ctl.active_media_kind() is None
    ctl._write(ctl.MEDIA_JOB_FILE, {
        "a": {"kind": "image", "status": "running", "native_job_id": "fictional"}
    })
    assert ctl.active_media_kind() == "image"
    ctl._write(ctl.MEDIA_JOB_FILE, {
        "a": {"kind": "image", "status": "completed", "native_job_id": "fictional"}
    })
    assert ctl.active_media_kind() is None


def test_inference_lease_prevents_termination_and_defers_later_extractions():
    ctl._write(ctl.STATE, {"updated_at": time.time(), "state": "running", "owned": True})
    with ctl.inference_lease():
        ctl.note_media_demand("video")
        manager = sup.Supervisor()
        manager.child = mock.Mock()
        manager.child.poll.return_value = None
        assert not manager.stop()
        manager.child.terminate.assert_not_called()
    with pytest.raises(ctl.DeferredMemoryInference):
        with ctl.inference_lease():
            pass


def test_pause_and_stale_supervisor_state():
    ctl._write(ctl.STATE, {"updated_at": time.time(), "pause_extraction": True})
    with pytest.raises(ctl.DeferredMemoryInference):
        with ctl.inference_lease():
            pass
    ctl._write(ctl.STATE, {"updated_at": time.time() - 100, "pause_extraction": True})
    with ctl.inference_lease():
        pass


def test_supervisor_never_kills_external_port(monkeypatch):
    manager = sup.Supervisor()
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(sup, "probe_port", lambda: True)
    with mock.patch.object(manager, "stop") as stop:
        manager.tick()
        assert ctl.supervisor_state()["state"] == "external"
        stop.assert_not_called()


def test_media_dispatch_waits_for_owned_model_to_release(monkeypatch):
    ctl._write(ctl.STATE, {"updated_at": time.time(), "owned": True, "state": "running"})
    monkeypatch.setattr(sup.rc, "memory_budget_snapshot",
                        lambda: {"free_percent": 17, "headroom_gb": 2})
    assert not ctl.prepare_media_dispatch("video", timeout_seconds=0.2)
    assert ctl.active_media_kind() == "video"
    ctl._write(ctl.STATE, {"updated_at": time.time(), "owned": False,
                            "state": "suspended_media"})
    assert ctl.prepare_media_dispatch("video", timeout_seconds=0.2)



def test_media_with_sufficient_headroom_does_not_block_memory_extraction():
    ctl._write(ctl.STATE, {"updated_at": time.time(), "state": "running",
                            "owned": True, "pause_extraction": False})
    ctl._write(ctl.MEDIA_JOB_FILE, {
        "a": {"kind": "image", "status": "running", "native_job_id": "fictional"}
    })
    assert ctl.active_media_kind() == "image"
    assert ctl.requested_media_priority() is None
    with ctl.inference_lease():
        pass  # Healthy coexistence: no unnecessary memory starvation.

def test_exclusive_image_preempts_4b_even_when_memory_is_healthy():
    safe = {"free_percent": 50, "headroom_gb": 20, "pressure": "normal"}
    assert not sup.should_unload(safe, "image")

    ctl.note_media_demand("image", exclusive=True)
    assert ctl.requested_media_priority() == "image"
    assert ctl.exclusive_media_requested("image")
    assert not ctl.exclusive_media_requested("video")
    assert sup.should_unload(safe, "image")

    # Once the handoff marker expires, normal pressure policy resumes.
    ctl._write(ctl.DEMAND, {
        "kind": "image", "exclusive": True, "until": time.time() - 1,
    })
    assert not ctl.exclusive_media_requested("image")
    assert not sup.should_unload(safe, "image")


def test_exclusive_media_handoff_waits_until_supervisor_child_is_gone(monkeypatch):
    ctl._write(ctl.STATE, {
        "updated_at": time.time(), "owned": True, "state": "running",
    })
    observations = []

    def unload_after_checkpoint(_seconds):
        observations.append(ctl.exclusive_media_requested("image"))
        ctl._write(ctl.STATE, {
            "updated_at": time.time(), "owned": False,
            "state": "suspended_media",
        })

    with mock.patch.object(ctl.time, "sleep", side_effect=unload_after_checkpoint):
        assert ctl.prepare_media_dispatch(
            "image", timeout_seconds=1, exclusive=True,
        )
    assert observations == [True]
    assert ctl.requested_media_priority() == "image"


def test_healthy_nonexclusive_media_stays_compatible_with_4b(monkeypatch):
    ctl._write(ctl.STATE, {
        "updated_at": time.time(), "owned": True, "state": "running",
    })
    monkeypatch.setattr(sup.rc, "memory_budget_snapshot",
                        lambda: {"free_percent": 50, "headroom_gb": 20})
    assert ctl.prepare_media_dispatch("image", timeout_seconds=0.1)
    assert ctl.requested_media_priority() is None
    assert not ctl.exclusive_media_requested("image")


def test_exclusive_handoff_never_terminates_external_4b(monkeypatch):
    ctl._write(ctl.STATE, {
        "updated_at": time.time(), "owned": False, "state": "external",
    })
    with pytest.raises(ctl.UnmanagedMemoryModel, match="4B"):
        ctl.prepare_media_dispatch(
            "image", timeout_seconds=0.1, exclusive=True,
        )
    assert ctl.requested_media_priority() is None
    manager = sup.Supervisor()
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(sup, "probe_port", lambda: True)
    with mock.patch.object(manager, "stop") as stop:
        manager.tick()
    stop.assert_not_called()


def test_direct_native_media_lease_keeps_supervisor_suspended_after_demand_expires(monkeypatch):
    import runtime_coordinator as rc
    monkeypatch.setattr(rc, "lease_state_snapshot",
                        lambda: {"active": {"workload": "video"}})
    ctl._write(ctl.DEMAND, {
        "kind": "video", "exclusive": True, "until": time.time() - 10,
    })
    assert ctl.active_media_kind() == "video"
    assert not sup.should_load({"free_percent": 85, "headroom_gb": 30},
                               ctl.active_media_kind())


def test_manual_4b_blocks_exclusive_video_without_killing_process(monkeypatch):
    monkeypatch.setattr(ctl, "_external_dedicated_model_running", lambda: True)
    with pytest.raises(ctl.UnmanagedMemoryModel, match="4B"):
        ctl.prepare_media_dispatch("video", timeout_seconds=0, exclusive=True)
    # Nonexclusive API semantics are unchanged.
    assert ctl.prepare_media_dispatch("video", timeout_seconds=0, exclusive=False)


def test_exclusive_video_waits_for_supervisor_owned_memory(monkeypatch):
    ctl._write(ctl.STATE, {
        "updated_at": time.time(), "owned": True, "state": "running",
    })
    monkeypatch.setattr(ctl, "_external_dedicated_model_running", lambda: False)
    def release(_duration):
        assert ctl.exclusive_media_requested("video")
        ctl._write(ctl.STATE, {
            "updated_at": time.time(), "owned": False,
            "state": "suspended_media",
        })
    monkeypatch.setattr(ctl.time, "sleep", release)
    assert ctl.prepare_media_dispatch("video", timeout_seconds=1, exclusive=True)


def test_owned_4b_resumes_after_media_finishes(monkeypatch):
    manager = sup.Supervisor()
    safe = {"free_percent": 50, "headroom_gb": 20, "pressure": "normal"}
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(sup, "probe_port", lambda: False)
    monkeypatch.setattr(sup.rc, "memory_budget_snapshot", lambda: safe)
    ctl.note_media_demand("image", exclusive=True)
    with mock.patch.object(manager, "start") as start:
        manager.tick()
    start.assert_not_called()
    # Terminal job + expired handoff allows the existing supervisor to reload.
    ctl._write(ctl.DEMAND, {"kind": "image", "exclusive": True,
                            "until": time.time() - 1})
    with mock.patch.object(manager, "start") as start:
        manager.tick()
    start.assert_called_once_with()
