"""CPU-only checks for safe chat performance profiles and long A/B probes."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

profile = load("nobby_profile", "chat-performance-profile.py")
benchmark = load("nobby_benchmark_ab", "benchmark-chat-experience.py")

def test_profile_settings_are_reversible_and_single_key():
    before = '# Nobby\nMODEL="/Users/example/Models/Qwen3.8"\nSPECULATIVE_DRAFT_KIND="dflash"\nexport EXISTING=1\n'
    apc = profile.updated_config(before, "apc")
    assert apc.count(profile.KEY) == 1
    assert profile.configured_profile(apc) == "apc"
    dflash = profile.updated_config(apc, "dflash")
    assert profile.configured_profile(dflash) == "dflash"
    assert profile.updated_config(dflash, "default") == before
    assert profile.updated_config(apc, "apc") == apc
    with pytest.raises(ValueError, match="Multiple"):
        profile.updated_config(apc + 'MLX_CHAT_PERFORMANCE_PROFILE="dflash"\n', "apc")
    for invalid in ("auto", "apc;rm -rf /", ""):
        with pytest.raises(ValueError):
            profile.updated_config(before, invalid)
    with pytest.raises(ValueError, match="Unknown/invalid"):
        profile.configured_profile('MLX_CHAT_PERFORMANCE_PROFILE="bad"\n')

def test_write_config_is_private_atomic(tmp_path):
    config = tmp_path / "config"
    config.write_text("before\n")
    config.chmod(0o600)
    profile.write_config("after\n", config)
    assert config.read_text() == "after\n"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config"]

def test_idle_guard_rejects_media_and_runtime_work(monkeypatch):
    snap = {"ok": True, "media": {"active_count": 0, "waiting_count": 0},
            "system": {"runtimes": {name: {"active": False}
                                    for name in ("chat", "image", "video")},
                       "runtime_lease": {"active": None, "waiting_count": 0}}}
    monkeypatch.setattr(profile, "json_get", lambda _: snap)
    profile.ensure_idle()
    for kind in ("chat", "image", "video"):
        snap["system"]["runtimes"][kind]["active"] = True
        with pytest.raises(RuntimeError, match="workload active"):
            profile.ensure_idle()
        snap["system"]["runtimes"][kind]["active"] = False
    snap["media"]["active_count"] = 1
    with pytest.raises(RuntimeError, match="Media queue"):
        profile.ensure_idle()
    snap["media"]["active_count"] = 0
    snap["system"]["runtime_lease"]["active"] = {"workload": "chat"}
    with pytest.raises(RuntimeError, match="lease"):
        profile.ensure_idle()
    snap["system"]["runtime_lease"]["active"] = None
    snap["system"]["runtime_lease"]["waiting_count"] = 1
    with pytest.raises(RuntimeError, match="lease"):
        profile.ensure_idle()

def test_missing_agent_status_fails_closed(monkeypatch):
    monkeypatch.setattr(profile, "json_get", lambda _: {"ok": True})
    with pytest.raises(RuntimeError, match="Incomplete"):
        profile.ensure_idle()

def test_select_profile_restarts_and_rechecks_health(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.write_text('SPECULATIVE_DRAFT_MODEL="draft"\n')
    monkeypatch.setattr(profile, "CONFIG", config)
    monkeypatch.setattr(profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(profile, "preflight", lambda mode: None)
    calls = []
    monkeypatch.setattr(profile, "restart", lambda: calls.append("restart"))
    monkeypatch.setattr(profile, "confirm_profile", lambda mode: calls.append(mode))
    assert profile.switch_profile("apc")
    assert profile.configured_profile(config.read_text()) == "apc"
    assert calls == ["restart", "apc"]
    assert not profile.switch_profile("apc")
    assert profile.switch_profile("default")
    assert config.read_text() == 'SPECULATIVE_DRAFT_MODEL="draft"\n'

def test_failed_switch_restores_original_config_and_restarts(monkeypatch, tmp_path):
    config = tmp_path / "config"
    original = 'MODEL="test"\n'
    config.write_text(original)
    monkeypatch.setattr(profile, "CONFIG", config)
    monkeypatch.setattr(profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(profile, "preflight", lambda mode: None)
    calls = []
    def confirm(mode):
        calls.append(mode)
        if mode == "apc":
            raise RuntimeError("simulated APC startup failure")
    monkeypatch.setattr(profile, "restart", lambda: calls.append("restart"))
    monkeypatch.setattr(profile, "confirm_profile", confirm)
    with pytest.raises(RuntimeError, match="startup failure"):
        profile.switch_profile("apc")
    assert config.read_text() == original
    assert calls == ["restart", "apc", "restart", "default"]

def test_live_apc_and_dflash_confirmation(monkeypatch):
    monkeypatch.setattr(profile, "json_get", lambda _: {
        "status": "healthy", "loaded_model": "test", "apc_enabled": True
    })
    monkeypatch.setattr(profile, "current_server_args", lambda: "mlx_vlm server --port 8000")
    profile.confirm_profile("apc")
    with pytest.raises(RuntimeError, match="APC still enabled"):
        profile.confirm_profile("dflash")
    monkeypatch.setattr(profile, "current_server_args", lambda: "mlx_vlm server --port 8000 --draft-model draft")
    with pytest.raises(RuntimeError, match="Unexpected speculative"):
        profile.confirm_profile("apc")
    monkeypatch.setattr(profile, "json_get", lambda _: {
        "status": "healthy", "loaded_model": "test", "apc_enabled": False
    })
    monkeypatch.setattr(profile, "current_server_args", lambda: "mlx_vlm server --port 8000 --draft-model draft --draft-kind dflash")
    profile.confirm_profile("dflash")

def test_apc_and_dflash_are_separate_server_modes():
    launcher = (ROOT / "scripts" / "mlx-server-start").read_text()
    assert 'CHAT_PERFORMANCE_PROFILE="${MLX_CHAT_PERFORMANCE_PROFILE:-default}"' in launcher
    assert 'export APC_ENABLED=1' in launcher
    assert 'export APC_EXACT_CACHE_ENTRIES=1' in launcher
    assert 'export APC_DISK_PATH=""' in launcher
    assert 'SPECULATIVE_TARGET_VALUE=""' in launcher
    assert 'export APC_ENABLED=0' in launcher
    assert '"$PROJECT_DIR/scripts/runtime-model-guard.py"' in launcher
    for name in ("mlx-server-start", "mlx"):
        result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

def test_long_answer_mode_uses_nontrivial_prompt(monkeypatch):
    captured = []
    snapshot = {"ok": True, "system": {"runtimes": {"chat": {"active": False}}},
                "model": {"recent_calls": []}}
    monkeypatch.setattr(benchmark, "request_json", lambda *_: snapshot)
    def fake_stream(_url, messages, *_):
        captured.append(messages)
        return ({"first_transport_ms": 1, "first_content_ms": 10,
                 "total_ms": 30, "output_characters": 1800}, "technical answer")
    monkeypatch.setattr(benchmark, "agent_stream", fake_stream)
    report = benchmark.run("http://127.0.0.1:8010", [4000], 1, 384, 30,
                           answer_profile="long")
    assert report["answer_profile"] == "long"
    assert "mindestens zehn" in captured[0][-1]["content"]
    assert "mindestens zehn" in captured[1][-1]["content"]
    assert captured[2][-1]["content"] == benchmark.LONG_QUESTION
    with pytest.raises(ValueError, match="Invalid"):
        benchmark.run("http://127.0.0.1:8010", [4000], 1, 384, 30,
                      answer_profile="malicious")
    assert "technical answer" not in json.dumps(report)

def test_compare_restores_original_profile_even_if_probe_raises(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.write_text("MODEL=example\n")
    monkeypatch.setattr(profile, "CONFIG", config)
    monkeypatch.setattr(profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(profile, "preflight", lambda mode: None)
    changed = []
    def switch(mode):
        changed.append(mode)
        config.write_text(profile.updated_config(config.read_text(), mode))
    monkeypatch.setattr(profile, "switch_profile", switch)
    runs = []
    def fake_run(*args, **kwargs):
        runs.append(profile.configured_profile(config.read_text()))
        if len(runs) == 2:
            raise RuntimeError("injected failure during APC inference")
        return {"short": {"first_content_ms": {"p50": 1},
                          "total_ms": {"p50": 2},
                          "samples": [{"output_characters": 1200}]},
                "contexts": []}
    monkeypatch.setattr(profile, "load_benchmark", lambda: SimpleNamespace(run=fake_run))
    with pytest.raises(RuntimeError, match="injected failure"):
        profile.compare(SimpleNamespace(context_sizes=[4000], samples=1,
                                       max_tokens=384, timeout=20))
    assert changed == ["dflash", "apc", "default"]
    assert profile.configured_profile(config.read_text()) == "default"
