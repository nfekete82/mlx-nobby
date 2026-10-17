"""CPU-only contract tests for hybrid long-form semantic + memory smoke."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-hybrid-longform.py"
SPEC = importlib.util.spec_from_file_location("nobby_longform_quality", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_synthetic_long_form_keeps_markers_only_in_initial_context():
    first, follow = gate.make_messages(4000)
    assert len(first) == 2
    assert len(first[1]["content"]) >= 16000
    assert all(marker in first[1]["content"] for marker in gate.MARKERS)
    assert all(marker not in follow["content"] for marker in gate.MARKERS)
    assert "Prefill" in follow["content"]
    assert "Die erste Ausgabezeile MUSS genau dieses Schema haben" in follow["content"]


def test_technical_and_canary_verifier_distinguishes_bad_output():
    good = (
        "AURORAFADEN SILBERBRUECKE WALDFENSTER. "
        "Prefill erstellt den Kontext, danach kommt Decoding mit Streaming."
    )
    assert all(gate.verify_long_answer(good, 1250, 400).values())
    bad = "Prefill mit Decoding und Streaming."
    checks = gate.verify_long_answer(bad, 27, 400)
    assert not checks["canaries_recalled"]
    assert checks["technical_terms_present"]
    assert not checks["long_enough"]
    assert gate.verify_long_answer("", 1800, 400)["captured_text_not_empty"] is False


def test_marker_diagnostics_identifies_exact_missing_and_format_only_matches():
    exact = (
        "Kennwort 1: AURORAFADEN; Kennwort 2: SILBERBRUECKE; "
        "Kennwort 3: WALDFENSTER."
    )
    result = gate.marker_diagnostics(exact + "\\nPrefill Decoding Streaming")
    assert all(result["exact"].values())
    assert all(result["normalized"].values())
    assert all(result["first_line_exact"].values())
    assert result["first_nonempty_line_characters"] > 40

    # Separator and umlaut variants must be *visible* in diagnostics, never
    # silently converted to strict recall success.
    variant = "Aurora-Faden; Silberbrücke; Wald-Fenster."
    diagnostic = gate.marker_diagnostics(variant)
    assert not any(diagnostic["exact"].values())
    assert all(diagnostic["normalized"].values())
    assert gate.verify_long_answer(variant, 1200, 400)["canaries_recalled"] is False

    missing = gate.marker_diagnostics("Kennwort 1: AURORAFADEN")
    assert missing["exact"]["AURORAFADEN"] is True
    assert missing["exact"]["SILBERBRUECKE"] is False
    assert missing["exact"]["WALDFENSTER"] is False
    assert "Kennwort 1:" not in json.dumps(diagnostic)


def test_memory_and_swap_bounds_fail_closed():
    gate.check_memory({"pressure": "normal", "headroom_gb": 6.5},
                      minimum_headroom_gb=6)
    for snap in (
        {"pressure": "elevated", "headroom_gb": 50},
        {"pressure": "normal", "headroom_gb": 5.9},
        {"pressure": "normal"},
    ):
        with pytest.raises(RuntimeError):
            gate.check_memory(snap, minimum_headroom_gb=6)
    assert gate.check_swap_delta(
        {"swap_used_gb": 12.0}, {"swap_used_gb": 12.1}, max_delta_gb=1
    ) == pytest.approx(0.1)
    with pytest.raises(RuntimeError, match="Swap growth"):
        gate.check_swap_delta(
            {"swap_used_gb": 12.0}, {"swap_used_gb": 13.1}, max_delta_gb=1
        )
    with pytest.raises(RuntimeError, match="telemetry unavailable"):
        gate.check_swap_delta({"swap_used_gb": None},
                              {"swap_used_gb": 13.1}, max_delta_gb=1)


def test_run_mode_validates_prime_quality_and_cache_hit(monkeypatch):
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    snapshot = {"pressure": "normal", "headroom_gb": 15,
                "free_percent": 40, "swap_used_gb": 18.9}
    monkeypatch.setattr(gate.profile, "memory_snapshot", lambda: snapshot)
    count = {"value": 0}
    def fake_cache():
        count["value"] += 1
        return {"exact_hits": 0 if count["value"] == 1 else 1}
    monkeypatch.setattr(gate.profile, "cache_snapshot", fake_cache)
    calls = []
    answer = (
        "AURORAFADEN SILBERBRUECKE WALDFENSTER. "
        "Prefill mit KV-Cache, danach Decoding und Streaming."
    )
    def fake_stream(_url, messages, _tokens, _timeout):
        calls.append(messages)
        return (
            {"first_content_ms": 10, "total_ms": 100,
             "output_characters": 1300},
            "START" if len(calls) == 1 else answer,
        )
    monkeypatch.setattr(gate.bench, "agent_stream", fake_stream)
    result, text = gate.run_mode("hybrid", 4000, 400, 100)
    assert result["passed"]
    assert result["exact_hits_after"] == 1
    assert result["checks"]["exact_cache_hit"] is True
    assert result["swap_delta_gb"] == 0.0
    assert text == answer
    assert len(calls[1]) == 4
    assert "AURORAFADEN" not in json.dumps(result)

    monkeypatch.setattr(
        gate.bench, "agent_stream",
        lambda *_: ({"first_content_ms": 10, "total_ms": 15,
                     "output_characters": 1}, "WRONG")
    )
    with pytest.raises(RuntimeError, match="prime correctly"):
        gate.run_mode("hybrid", 4000, 400, 100)


def test_compare_returns_similarity_and_restores_original(monkeypatch):
    cfg = {"value": 'MODEL="synthetic"\n'}
    monkeypatch.setattr(
        gate.profile, "CONFIG", SimpleNamespace(
            read_text=lambda **_: cfg["value"]
        )
    )
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(gate.profile, "preflight", lambda _: None)
    switched = []
    def switch(mode):
        switched.append(mode)
        cfg["value"] = gate.profile.updated_config(cfg["value"], mode)
    monkeypatch.setattr(gate.profile, "switch_profile", switch)
    synthetic = (
        "AURORAFADEN SILBERBRUECKE WALDFENSTER "
        "Prefill Decoding Streaming"
    )
    def run(mode, *_):
        return {"profile": mode, "passed": True}, synthetic
    monkeypatch.setattr(gate, "run_mode", run)
    result = gate.compare_longform(4000, 400, 180)
    assert result["passed"]
    assert result["comparison"]["near_identical"]
    assert result["comparison"]["captured_text_similarity_ratio"] == 1.0
    assert result["starting_profile_restored"] == "default"
    assert switched == ["dflash", "hybrid", "default"]
    assert cfg["value"] == 'MODEL="synthetic"\n'
    assert "AURORAFADEN" not in json.dumps(result)


def test_failed_long_form_restores_previous_config(monkeypatch):
    cfg = {"value": 'MODEL="synthetic"\n'}
    monkeypatch.setattr(
        gate.profile, "CONFIG", SimpleNamespace(
            read_text=lambda **_: cfg["value"]
        )
    )
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(gate.profile, "preflight", lambda _: None)
    seen = []
    def switch(mode):
        seen.append(mode)
        cfg["value"] = gate.profile.updated_config(cfg["value"], mode)
    monkeypatch.setattr(gate.profile, "switch_profile", switch)
    def fail_hybrid(mode, *_):
        if mode == "hybrid":
            raise RuntimeError("Simulated unsafe hybrid failure")
        return {"passed": True}, "BASELINE"
    monkeypatch.setattr(gate, "run_mode", fail_hybrid)
    with pytest.raises(RuntimeError, match="unsafe hybrid"):
        gate.compare_longform(4000, 400, 180)
    assert seen == ["dflash", "hybrid", "default"]
    assert cfg["value"] == 'MODEL="synthetic"\n'
