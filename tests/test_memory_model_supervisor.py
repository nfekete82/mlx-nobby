"""Six bounded unit checks; no model start, personal SQLite or media dispatch."""
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
