"""Offline regression tests for the optional chat idle watchdog.

No model, API, launchd or personal-memory data is used.
"""
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


@pytest.fixture
def mgr():
    path = Path(__file__).resolve().parents[1] / "scripts/chat-idle-manager.py"
    spec = importlib.util.spec_from_file_location("nobby_chat_idle_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample(mgr, **kwargs):
    data = dict(model="model-27b", requests_started=5, in_flight=0,
                queue_depth=0, agent_runs=0, last_request_at=1234)
    data.update(kwargs)
    return mgr.Snapshot(**data)


def test_full_ten_minute_idle_grace_and_request_counter_reset(mgr):
    tracker = mgr.IdleTracker()
    first = sample(mgr)
    assert tracker.observe(first, 1000) == 0
    assert tracker.observe(first, 1599) == 599
    assert tracker.observe(first, 1600) == 600
    newer = sample(mgr, requests_started=6, last_request_at=1601)
    assert tracker.observe(newer, 1601) == 0
    assert tracker.observe(newer, 1701) == 100


def test_active_stream_queued_request_and_agent_execution_reset_idle(mgr):
    for kwargs in ({"in_flight": 1}, {"queue_depth": 1}, {"agent_runs": 1}):
        tracker = mgr.IdleTracker()
        tracker.observe(sample(mgr), 10)
        assert tracker.observe(sample(mgr, **kwargs), 710) == 0
        assert tracker.since is None
        assert tracker.observe(sample(mgr), 715) == 0


def test_unloaded_or_failed_probe_clears_idle(mgr):
    tracker = mgr.IdleTracker()
    tracker.observe(sample(mgr), 100)
    assert tracker.observe(None, 200) == 0
    assert tracker.observe(sample(mgr), 900) == 0
    assert tracker.observe(sample(mgr, model=None), 1500) == 0


def test_probe_fails_closed_when_required_metric_missing(mgr, monkeypatch):
    health = {"status": "healthy", "loaded_model": "model-27b"}
    metrics = {"summary": {"requests_started": 5, "in_flight": 0, "last_request_at": 123},
               "server": {"loaded_model": "model-27b", "loaded_models": ["model-27b"]}}
    agent = {"status": "ok", "active_agent_runs": 0}

    def get(port, path, **_kwargs):
        return {
            (8000, "/health"): health,
            (8000, "/metrics"): metrics,
            (8010, "/api/runtime/reliability"): agent,
        }[(port, path)]

    monkeypatch.setattr(mgr, "_json_get", get)
    with pytest.raises(mgr.ProbeUnavailable, match="request_queue_depth"):
        mgr.probe()
    metrics["server"]["request_queue_depth"] = 0
    assert mgr.probe().idle
    metrics["summary"]["in_flight"] = True  # bool isn't an integer counter
    with pytest.raises(mgr.ProbeUnavailable, match="in_flight"):
        mgr.probe()
    metrics["summary"]["in_flight"] = 0
    metrics["server"]["loaded_model"] = "other model"
    with pytest.raises(mgr.ProbeUnavailable, match="Model changed"):
        mgr.probe()
    metrics["server"]["loaded_model"] = "model-27b"
    metrics["server"]["loaded_models"] = ["model-27b", "other"]
    with pytest.raises(mgr.ProbeUnavailable, match="Multiple"):
        mgr.probe()


def test_unload_never_runs_if_new_request_arrives_between_probes(mgr, monkeypatch):
    baseline = sample(mgr)
    seq = iter([baseline, sample(mgr, requests_started=6, last_request_at=5678)])

    @contextmanager
    def guard():
        yield

    monkeypatch.setattr(mgr, "_runtime_guard", guard)
    monkeypatch.setattr(mgr, "probe", lambda: next(seq))
    monkeypatch.setattr(mgr.time, "sleep", lambda _: None)
    monkeypatch.setattr(mgr, "_unload", lambda: pytest.fail("unload must not happen"))
    assert mgr.attempt_unload(baseline) == "request_changed"


def test_unload_is_serialized_and_verified_without_process_kill(mgr, monkeypatch):
    baseline = sample(mgr)
    events = []

    @contextmanager
    def guard():
        events.append("lock")
        yield
        events.append("unlock")

    monkeypatch.setattr(mgr, "_runtime_guard", guard)
    monkeypatch.setattr(mgr, "probe", lambda: baseline)
    monkeypatch.setattr(mgr.time, "sleep", lambda _: None)
    monkeypatch.setattr(mgr, "_unload", lambda: events.append("unload"))
    monkeypatch.setattr(mgr, "_json_get", lambda *_a, **_k: {"loaded_model": None})
    assert mgr.attempt_unload(baseline) == "unloaded"
    assert events == ["lock", "unload", "unlock"]


def test_check_is_read_only(mgr, monkeypatch, capsys):
    monkeypatch.setattr(mgr, "probe", lambda: sample(mgr))
    monkeypatch.setattr(mgr, "_unload", lambda: pytest.fail("read-only check issued unload"))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert mgr.main(["--check"]) == 0
    assert '"action":"read_only"' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        mgr.main(["--check", "--apply"])
