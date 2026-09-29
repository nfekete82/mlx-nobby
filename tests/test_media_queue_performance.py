import threading
from types import SimpleNamespace

from agent import media_queue_performance as performance


def fake_media_module():
    writes = []
    job_id = "a" * 24
    jobs = {
        job_id: {
            "id": job_id,
            "status": "running",
            "phase": "running",
            "progress": 0.1,
            "current_step": 1,
            "total_steps": 10,
        }
    }

    module = SimpleNamespace(
        _jobs_lock=threading.RLock(),
        _jobs=jobs,
        TERMINAL=frozenset({"completed", "failed", "cancelled"}),
        _ensure_loaded_locked=lambda: None,
        _persist_locked=lambda: writes.append("persist"),
        _public=lambda job: dict(job),
    )
    return module, job_id, writes


def test_identical_poll_does_not_persist(monkeypatch):
    module, job_id, writes = fake_media_module()
    performance.reset_state()
    update = performance._optimized_update(module)

    result = update(
        job_id,
        status="running",
        phase="running",
        progress=0.1,
        current_step=1,
        total_steps=10,
    )

    assert result["progress"] == 0.1
    assert writes == []


def test_progress_only_updates_are_throttled(monkeypatch):
    module, job_id, writes = fake_media_module()
    performance.reset_state()
    monkeypatch.setattr(performance, "PROGRESS_PERSIST_INTERVAL", 1.5)

    now = iter([10.0, 10.5, 11.6])
    monkeypatch.setattr(performance.time, "monotonic", lambda: next(now))
    update = performance._optimized_update(module)

    update(job_id, progress=0.2, current_step=2)
    update(job_id, progress=0.3, current_step=3)
    update(job_id, progress=0.4, current_step=4)

    assert writes == ["persist", "persist"]
    assert module._jobs[job_id]["progress"] == 0.4
    assert module._jobs[job_id]["current_step"] == 4


def test_status_and_terminal_changes_persist_immediately(monkeypatch):
    module, job_id, writes = fake_media_module()
    performance.reset_state()
    monkeypatch.setattr(performance.time, "monotonic", lambda: 20.0)
    update = performance._optimized_update(module)

    update(job_id, phase="saving")
    update(
        job_id,
        status="completed",
        phase="completed",
        progress=1.0,
        finished_at=123.0,
    )

    assert writes == ["persist", "persist"]
    assert module._jobs[job_id]["status"] == "completed"
    assert job_id not in performance._last_progress_persist_at


def test_terminal_job_cannot_be_moved_back_to_running(monkeypatch):
    module, job_id, writes = fake_media_module()
    module._jobs[job_id]["status"] = "completed"
    performance.reset_state()
    update = performance._optimized_update(module)

    result = update(job_id, status="running", progress=0.5)

    assert result["status"] == "completed"
    assert writes == []
