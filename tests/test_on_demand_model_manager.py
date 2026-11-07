"""Synthetic on-demand 4B checks: no real models, launchd or private data."""
import io
import json
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from agent import memory_model_coordination as ctl
from agent import memory_model_supervisor as sup
from agent import router_gateway as gateway
import runtime_coordinator as rc


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for attr, filename in {
        "ROOT": ".", "STATE": "supervisor.json",
        "DEMAND": "media-demand.json", "ROUTER_DEMAND": "router-demand.json",
        "INFERENCE_DEMAND": "inference-demand.json",
        "ON_DEMAND": "on-demand.json", "LOCK": "inference.lock",
        "MEDIA_JOB_FILE": "jobs.json", "MEMORY_DB": "personal-memory.sqlite3",
        "MEMORY_CONTROL": "memory-control.json",
    }.items():
        monkeypatch.setattr(ctl, attr, tmp_path if attr == "ROOT" else tmp_path / filename)


def test_default_policy_is_off_and_demand_markers_contain_no_messages():
    assert not ctl.on_demand_enabled()
    ctl._write(ctl.ON_DEMAND, {"enabled": True})
    assert ctl.on_demand_enabled()
    ctl.request_router_demand(seconds=30)
    ctl.request_memory_demand(seconds=30)
    assert ctl.router_demand_active()
    assert ctl.memory_demand_active()
    for p in (ctl.ROUTER_DEMAND, ctl.INFERENCE_DEMAND):
        assert set(json.loads(p.read_text())) == {"until"}
        assert p.stat().st_mode & 0o077 == 0


def test_supervisor_on_demand_is_off_without_actual_request(monkeypatch):
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: True)
    monkeypatch.setattr(ctl, "router_demand_active", lambda: False)
    monkeypatch.setattr(ctl, "memory_demand_active", lambda: False)
    safe = {"free_percent": 80, "headroom_gb": 30, "total_gb": 48, "used_estimate_gb": 10}
    assert sup.should_load(safe) is False
    assert sup.should_unload(safe, idle_expired=True) is True
    assert sup.should_unload(safe, idle_expired=False) is False
    monkeypatch.setattr(ctl, "router_demand_active", lambda: True)
    assert sup.should_load(safe) is True
    assert sup.should_unload(safe, idle_expired=True) is False


def test_router_request_triggers_single_supervised_backend(monkeypatch):
    """The gateway has no own model or child-Popen and relays to 8011 only."""
    events = []

    @contextmanager
    def lease(**kwargs):
        events.append(("runtime-lease", kwargs["workload"]))
        yield {}

    @contextmanager
    def memory():
        events.append(("memory-lease",))
        yield

    class FakeResponse:
        def __enter__(self):
            return io.BytesIO(b'{"choices":[{"message":{"content":"normal_chat"}}]}')
        def __exit__(self, *_):
            return False

    def opener(request, timeout):
        events.append(("upstream", request.full_url))
        assert request.full_url == "http://127.0.0.1:8011/v1/chat/completions"
        assert json.loads(request.data)["model"] == str(sup.MODEL)
        return FakeResponse()

    monkeypatch.setattr(rc, "runtime_lease", lease)
    monkeypatch.setattr(ctl, "inference_lease", memory)
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: True)
    monkeypatch.setattr(ctl, "active_media_kind", lambda: None)
    monkeypatch.setattr(ctl, "request_router_demand",
                        lambda **kw: events.append(("demand",)))
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(gateway, "_ready", lambda: True)
    monkeypatch.setattr(gateway._OPENER, "open", opener)

    result = gateway.complete({
        "model": str(sup.MODEL), "messages": [
            {"role": "user", "content": "synthetic hello"},
        ], "stream": False,
    })
    assert result["choices"][0]["message"]["content"] == "normal_chat"
    assert events == [
        ("runtime-lease", "router"), ("demand",), ("memory-lease",),
        ("upstream", "http://127.0.0.1:8011/v1/chat/completions"),
    ]
    assert gateway.health()["loaded"] is False


def test_gateway_refuses_media_preemption_or_wrong_model(monkeypatch):
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: True)
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(ctl, "active_media_kind", lambda: "image")
    with pytest.raises(gateway.RouterUnavailable):
        gateway._wait_for_model(timeout=0.01)
    with pytest.raises(ValueError, match="model"):
        gateway.complete({"model": "foreign model"})
    with pytest.raises(ValueError, match="Streaming"):
        gateway.complete({"stream": True})


def test_media_requires_gateway_if_on_demand_policy_is_enabled(monkeypatch):
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: True)
    with mock.patch.object(rc, "request_json", return_value={
        "router_manager": "legacy", "loaded": True,
    }), mock.patch.object(ctl, "prepare_media_dispatch") as dispatch:
        with pytest.raises(rc.ServiceUnavailable, match="Legacy"):
            rc._exclusive_memory_model_handoff("image")
        dispatch.assert_not_called()
    with mock.patch.object(rc, "request_json", return_value={
        "router_manager": "shared-4b", "model_manager_version": 1,
        "loaded": False, "active_generation": False,
    }), mock.patch.object(ctl, "prepare_media_dispatch", return_value=True) as dispatch:
        rc._exclusive_memory_model_handoff("video")
    dispatch.assert_called_once_with("video", exclusive=True)


def test_supervisor_does_not_interrupt_active_inference_when_idle(monkeypatch):
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: True)
    monkeypatch.setattr(ctl, "router_demand_active", lambda: False)
    monkeypatch.setattr(ctl, "memory_demand_active", lambda: False)
    monkeypatch.setattr(ctl, "active_media_kind", lambda: None)
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(sup.rc, "memory_budget_snapshot",
                        lambda: {"free_percent": 60, "total_gb": 48, "used_estimate_gb": 15})
    manager = sup.Supervisor()
    manager.child = mock.Mock()
    manager.child.poll.return_value = None
    manager.started_at = time.monotonic()
    manager.idle_since = time.monotonic() - sup.IDLE_UNLOAD_SECONDS - 1
    stop = mock.Mock(return_value=False)  # Shared inference lock is held.
    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "publish", lambda *args, **kwargs: None)
    manager.tick()
    stop.assert_called_once()


def test_old_default_remains_legacy_when_new_policy_not_enabled(monkeypatch):
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: False)
    monkeypatch.setattr(ctl, "router_demand_active", lambda: False)
    monkeypatch.setattr(ctl, "memory_demand_active", lambda: False)
    snap = {"free_percent": 70, "total_gb": 48, "used_estimate_gb": 20}
    assert sup.should_load(snap) is True
    assert sup.should_unload(snap, idle_expired=True) is False


def test_switcher_check_resolves_agent_when_invoked_as_script_from_other_cwd(tmp_path):
    """Regression: python scripts/switch-... must import agent without PYTHONPATH."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform != "darwin":
        pytest.skip("The switcher intentionally requires macOS")
    script = Path(__file__).resolve().parents[1] / "scripts" / "switch-shared-4b-router.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert isinstance(info["on_demand"], bool)
    assert isinstance(info["gateway_healthy"], bool)
    assert "supervisor_state" in info


def _router_switch_module():
    """Load the switcher without invoking CLI or launchctl."""
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "switch-shared-4b-router.py"
    spec = importlib.util.spec_from_file_location("router_switch_race_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_switcher_waits_for_delayed_gateway_listener(monkeypatch):
    switch = _router_switch_module()
    calls = []
    replies = iter([
        OSError("Connection refused"),
        {"router_manager": "legacy", "loaded": True},
        {"router_manager": "shared-4b", "loaded": False},
    ])

    def json_get(port):
        assert port == 8040
        calls.append("probe")
        reply = next(replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(switch, "_json_get", json_get)
    monkeypatch.setattr(switch.time, "sleep", lambda _delay: None)
    assert switch._wait_gateway_ready(timeout=5)["loaded"] is False
    assert calls == ["probe", "probe", "probe"]


def test_failed_gateway_readiness_restores_legacy_policy(monkeypatch, tmp_path):
    switch = _router_switch_module()
    import plistlib

    original = plistlib.dumps({"Label": switch.LABEL, "ProgramArguments": ["legacy"]})
    candidate = plistlib.dumps({"Label": switch.LABEL, "ProgramArguments": ["gateway"]})
    plist = tmp_path / "router.plist"
    plist.write_bytes(original)
    monkeypatch.setattr(switch, "ROOT", Path.home() / "mlx-web")
    monkeypatch.setattr(switch, "ROUTER_PLIST", plist)
    monkeypatch.setattr(switch, "LEGACY", tmp_path / "router-original.plist")
    monkeypatch.setattr(switch, "_check_backup", lambda _path: None)
    monkeypatch.setattr(switch, "_idle", lambda: None)
    monkeypatch.setattr(switch, "_idle_without_lease", lambda: None)
    monkeypatch.setattr(switch, "_render_gateway", lambda: candidate)
    monkeypatch.setattr(sup, "valid_settings", lambda: True)
    monkeypatch.setattr(ctl, "supervisor_state", lambda: {"owned": True, "state": "running"})
    monkeypatch.setattr(ctl, "on_demand_enabled", lambda: False)

    events = []
    monkeypatch.setattr(switch, "_policy", lambda value: events.append(("policy", value)))
    monkeypatch.setattr(switch, "_reload", lambda data: events.append(("reload", data)))

    @contextmanager
    def lease(**_kwargs):
        yield {}

    monkeypatch.setattr(rc, "runtime_lease", lease)

    def not_ready():
        events.append(("probe", None))
        raise RuntimeError("Simulated gateway bind failure")

    monkeypatch.setattr(switch, "_wait_gateway_ready", not_ready)
    with pytest.raises(RuntimeError, match="restored"):
        switch.enable(tmp_path)

    assert switch.LEGACY.read_bytes() == original
    assert events == [
        ("policy", True), ("reload", candidate), ("probe", None),
        ("reload", original), ("policy", False),
    ]
