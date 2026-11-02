"""Offline safety tests for the opt-in sequential Qwen model comparison."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "nobby_sequential_model_ab", ROOT / "scripts/benchmark-qwen38-model-ab.py"
)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


def test_pure_config_patch_preserves_other_settings():
    before = (
        '# live config\nMODEL="/tmp/6bit"\n'
        'SPECULATIVE_TARGET="/tmp/4bit"\n'
        'SPECULATIVE_DRAFT_MODEL="/tmp/draft"\n'
        'SPECULATIVE_DRAFT_KIND="dflash"\n'
        'THINKING="false"\n'
    )
    after = ab.replace_values(before, {
        "MODEL": "/tmp/4bit", "MLX_CHAT_PERFORMANCE_PROFILE": "dflash",
    })
    assert ab.config_value(after, "MODEL") == "/tmp/4bit"
    assert ab.config_value(after, "MLX_CHAT_PERFORMANCE_PROFILE") == "dflash"
    assert 'THINKING="false"' in after
    assert 'SPECULATIVE_TARGET="/tmp/4bit"' in after
    with pytest.raises(ValueError, match="Ambiguous"):
        ab.replace_values(before + 'MODEL="/tmp/other"\n', {"MODEL": "/tmp/4bit"})
    with pytest.raises(ValueError, match="Unsupported"):
        ab.replace_values(before, {"PORT": "9000"})


def test_memory_admission_fails_closed():
    good = dict(free_percent=35, headroom_gb=12, swap_used_gb=4, pressure="normal")
    assert ab.memory_gate(good) == []
    assert "swap_used_gb above" in "; ".join(ab.memory_gate({**good, "swap_used_gb": 12.5}))
    assert "memory pressure" in "; ".join(ab.memory_gate({**good, "pressure": "elevated"}))
    assert "unavailable" in "; ".join(ab.memory_gate({"free_percent": 30}))


def test_swap_interval_parser_uses_second_row_only():
    output = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "  free  active  swapins swapouts\n"
        "  5000  12000  56572K   76198K\n"
        "  5100  12010  256      0\n"
    )
    assert ab.parse_vm_stat_swap_delta(output, 3) == {
        "window_seconds": 3, "swapins_pages": 256, "swapouts_pages": 0,
    }
    with pytest.raises(ValueError, match="unavailable"):
        ab.parse_vm_stat_swap_delta("invalid output", 3)
    with pytest.raises(ValueError, match="malformed"):
        ab.parse_vm_stat_swap_delta(output.replace("256      0", "256      1K"), 3)


def test_high_historical_swap_requires_verified_zero_swapouts():
    high = dict(free_percent=88, headroom_gb=36.24,
                swap_used_gb=11.58, pressure="normal")
    inactive = {"window_seconds": 3, "swapins_pages": 200, "swapouts_pages": 0}
    assert ab.memory_gate(high, inactive) == []
    assert ab.memory_gate(high, {"window_seconds": 3, "swapouts_pages": 1}) == [
        "active swapouts detected"
    ]
    assert "not verified" in "; ".join(ab.memory_gate(high))
    assert ab.memory_gate({**high, "pressure": "critical"}, inactive) == [
        "memory pressure is not normal"
    ]


def setup_fake_runtime(tmp_path, monkeypatch):
    current = tmp_path / "6-bit"
    candidate = tmp_path / "4-bit"
    draft = tmp_path / "draft"
    for directory in (current, candidate, draft):
        directory.mkdir()
        (directory / "config.json").write_text('{"model_type":"qwen3_5"}')
    config = tmp_path / "config"
    original = (
        f'MODEL="{current}"\n'
        f'SPECULATIVE_TARGET="{candidate}"\n'
        f'SPECULATIVE_DRAFT_MODEL="{draft}"\n'
        'SPECULATIVE_DRAFT_KIND="dflash"\n'
        'THINKING="false"\n'
    )
    config.write_text(original)
    profile = ab.load_module("nobby_ab_profile_test", "chat-performance-profile.py")
    monkeypatch.setattr(profile, "CONFIG", config)
    monkeypatch.setattr(profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(profile, "memory_snapshot",
                        lambda: dict(free_percent=40, headroom_gb=14,
                                     swap_used_gb=3, pressure="normal"))
    monkeypatch.setattr(profile, "json_get",
                        lambda _: {"status": "healthy", "loaded_model": "present",
                                   "apc_enabled": False})
    monkeypatch.setattr(profile, "confirm_profile", lambda _: None)
    def args():
        active = ab.config_value(config.read_text(), "MODEL")
        suffix = " --draft-model " + str(draft) + " --draft-kind dflash" if active == str(candidate) else ""
        return f"python -m mlx_vlm server --port 8000 --model {active}" + suffix
    monkeypatch.setattr(profile, "current_server_args", args)
    restarts = []
    monkeypatch.setattr(profile, "restart", lambda: restarts.append(config.read_text()))
    monkeypatch.setattr(ab, "speed_tests", lambda _probe, model, *_:
                        {"model_speed": 40 if model == str(candidate) else 14})
    opts = SimpleNamespace(confirm_restarts=True, candidate_model=None,
                           samples=2, timeout=30, with_quality=False, output=None)
    return profile, config, original, restarts, opts


def test_plan_does_not_restart_or_write(monkeypatch, tmp_path, capsys):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    options.confirm_restarts = False
    assert ab.run(options, profile, object(), object()) == 0
    assert config.read_text() == original
    assert not restarts
    assert '"ready": true' in capsys.readouterr().out


def test_idle_guard_failure_is_named_and_other_diagnostics_still_run(monkeypatch, tmp_path, capsys):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    def guard():
        raise RuntimeError("Runtime lease active or queued; wait before switching")
    monkeypatch.setattr(profile, "ensure_idle", guard)
    options.confirm_restarts = False
    assert ab.run(options, profile, object(), object()) == 0
    import json
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert report["status"]["idle_check"] == "runtime_lease_busy"
    assert report["status"]["memory"]["headroom_gb"] == 14
    assert report["status"]["runtime_health"]["healthy"] is True
    assert "Idle guard blocked (runtime_lease_busy)" in report["blockers"]
    assert config.read_text() == original
    assert not restarts


def test_idle_guard_failure_prevents_restart_even_with_good_memory(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "ensure_idle", lambda: (_ for _ in ()).throw(
        RuntimeError("Incomplete runtime status; refusing profile change")))
    with pytest.raises(RuntimeError, match="runtime_status_incomplete"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert not restarts


def test_unknown_guard_errors_are_redacted():
    assert ab.idle_error_code(RuntimeError("private response body from upstream")) == "idle_guard_unavailable"
    assert ab.idle_error_code(RuntimeError("Media queue active; wait before switching")) == "media_queue_busy"


def test_high_swap_plan_passes_only_with_fresh_inactive_sample(monkeypatch, tmp_path, capsys):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "memory_snapshot",
                        lambda: dict(free_percent=88, headroom_gb=36.24,
                                     swap_used_gb=11.58, pressure="normal"))
    monkeypatch.setattr(ab, "sample_swap_activity",
                        lambda: {"window_seconds": 3, "swapins_pages": 256, "swapouts_pages": 0})
    options.confirm_restarts = False
    assert ab.run(options, profile, object(), object()) == 0
    import json
    plan = json.loads(capsys.readouterr().out)
    assert plan["ready"] is True
    assert plan["status"]["swap_activity"]["swapouts_pages"] == 0
    assert config.read_text() == original
    assert restarts == []


def test_active_swapout_plan_remains_blocked(monkeypatch, tmp_path, capsys):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "memory_snapshot",
                        lambda: dict(free_percent=88, headroom_gb=36.24,
                                     swap_used_gb=11.58, pressure="normal"))
    monkeypatch.setattr(ab, "sample_swap_activity",
                        lambda: {"window_seconds": 3, "swapins_pages": 0, "swapouts_pages": 1})
    options.confirm_restarts = False
    assert ab.run(options, profile, object(), object()) == 0
    import json
    plan = json.loads(capsys.readouterr().out)
    assert plan["ready"] is False
    assert "active swapouts detected" in plan["blockers"]
    assert config.read_text() == original
    assert not restarts


def test_vm_stat_failure_blocks_benchmark(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "memory_snapshot",
                        lambda: dict(free_percent=88, headroom_gb=36.24,
                                     swap_used_gb=11.58, pressure="normal"))
    monkeypatch.setattr(ab, "sample_swap_activity",
                        lambda: (_ for _ in ()).throw(ValueError("measurement failed")))
    with pytest.raises(RuntimeError, match="Preflight blocked"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert not restarts


def test_comparison_restores_entire_config_on_success(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    assert ab.run(options, profile, object(), object()) == 0
    assert config.read_text() == original
    assert len(restarts) == 2
    assert 'MLX_CHAT_PERFORMANCE_PROFILE="dflash"' in restarts[0]
    assert restarts[1] == original


def test_only_expected_model_drift_can_be_reconciled():
    original = 'MODEL="/models/6bit"\nTHINKING="false"\n'
    candidate = 'MODEL="/models/4bit"\nTHINKING="false"\nMLX_CHAT_PERFORMANCE_PROFILE="dflash"\n'
    role_switched = 'MODEL="/models/6bit"\nTHINKING="false"\nMLX_CHAT_PERFORMANCE_PROFILE="dflash"\n'
    assert ab.only_expected_model_drift(candidate, candidate, original)
    assert ab.only_expected_model_drift(role_switched, candidate, original)
    assert not ab.only_expected_model_drift(
        role_switched.replace('THINKING="false"', 'THINKING="true"'),
        candidate, original,
    )
    assert not ab.only_expected_model_drift(
        role_switched.replace('/models/6bit', '/models/unrelated'),
        candidate, original,
    )


def test_quality_error_after_role_switch_still_restores_baseline(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    options.with_quality = True
    state = {"calls": 0}
    def quality_run(_path, _timeout):
        state["calls"] += 1
        if state["calls"] == 1:
            return {"baseline": True}
        # Simulate the historical Agent role resolver changing MODEL
        # and failing in the first streamed quality case.
        interim = config.read_text().replace(
            ab.config_value(config.read_text(), "MODEL"),
            ab.config_value(original, "MODEL"),
        )
        config.write_text(interim)
        raise RuntimeError("Agent stream error")
    monkeypatch.setattr(ab, "quality_test", quality_run)
    with pytest.raises(RuntimeError, match="Agent stream error"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert len(restarts) == 2


def test_quality_error_preserves_unrelated_external_changes(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    options.with_quality = True
    state = {"calls": 0}
    def quality_run(_path, _timeout):
        state["calls"] += 1
        if state["calls"] == 1:
            return {"baseline": True}
        config.write_text(config.read_text().replace(
            'THINKING="false"', 'THINKING="true"',
        ))
        raise RuntimeError("Agent stream error")
    monkeypatch.setattr(ab, "quality_test", quality_run)
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        ab.run(options, profile, object(), object())
    assert 'THINKING="true"' in config.read_text()
    assert len(restarts) == 1


def test_inference_failure_restores_original_config(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    def broken(_probe, model, *_):
        if "4-bit" in model:
            raise RuntimeError("Synthetic candidate failure")
        return {"ok": True}
    monkeypatch.setattr(ab, "speed_tests", broken)
    with pytest.raises(RuntimeError, match="Synthetic candidate failure"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert len(restarts) == 2


def test_blocked_memory_prevents_any_switch(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(profile, "memory_snapshot",
                        lambda: dict(free_percent=24, headroom_gb=4,
                                     swap_used_gb=12.6, pressure="elevated"))
    with pytest.raises(RuntimeError, match="Preflight blocked"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert not restarts


def test_missing_candidate_prevents_any_switch(monkeypatch, tmp_path):
    profile, config, original, restarts, options = setup_fake_runtime(tmp_path, monkeypatch)
    candidate = Path(ab.config_value(original, "SPECULATIVE_TARGET"))
    (candidate / "config.json").unlink()
    with pytest.raises(RuntimeError, match="candidate model is not present"):
        ab.run(options, profile, object(), object())
    assert config.read_text() == original
    assert not restarts
