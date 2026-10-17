"""CPU-only checks for opt-in hybrid synthetic correctness gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-hybrid-correctness.py"
SPEC = importlib.util.spec_from_file_location("nobby_hybrid_correctness", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_synthetic_prompt_and_normalization():
    first, follow = gate.synthetic_turns(4000)
    assert len(first) == 2
    assert len(first[1]["content"]) > 16000
    assert "MONDFALTER" in first[1]["content"]
    assert "Welches CODEWORT" in follow
    assert gate.normalize(' "mondfalter".  ') == "MONDFALTER"
    assert gate.normalize('START') == "START"
    assert gate.normalize('START irgendwas') != "START"


def test_memory_guard_fails_closed():
    gate.safety_memory_check({"pressure": "normal", "headroom_gb": 7})
    with pytest.raises(RuntimeError, match="pressure"):
        gate.safety_memory_check({"pressure": "elevated", "headroom_gb": 100})
    with pytest.raises(RuntimeError, match="headroom"):
        gate.safety_memory_check({"pressure": "normal", "headroom_gb": 5})
    with pytest.raises(RuntimeError, match="headroom"):
        gate.safety_memory_check({"pressure": "normal"})


def test_probe_requires_correct_answer_and_a_real_cache_hit(monkeypatch):
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(
        gate.profile, "memory_snapshot",
        lambda: {"pressure": "normal", "headroom_gb": 15},
    )
    calls = []
    def fake_cache():
        return {"exact_hits": 0 if not calls else 1}
    monkeypatch.setattr(gate.profile, "cache_snapshot", fake_cache)
    monkeypatch.setattr(gate.bench, "request_json", lambda *_: {"ok": True})
    monkeypatch.setattr(gate.bench, "check_idle", lambda _: None)
    def fake_stream(_url, messages, *_):
        calls.append(messages)
        return ({"first_content_ms": 100, "total_ms": 200},
                "START" if len(calls) == 1 else "MONDFALTER")
    monkeypatch.setattr(gate.bench, "agent_stream", fake_stream)
    check = gate.test_profile("hybrid", 4000, 120)
    assert check["passed"]
    assert all(check["checks"].values())
    assert check["exact_cache_hits_after"] == 1
    assert len(calls[1]) == 4
    assert calls[1][:2] == calls[0]
    assert "MONDFALTER" not in json.dumps(check)
    monkeypatch.setattr(
        gate.bench, "agent_stream",
        lambda *_: ({"first_content_ms": 100, "total_ms": 200}, "WRONG"),
    )
    assert not gate.test_profile("hybrid", 4000, 120)["passed"]


def test_validate_restores_default_after_failure(monkeypatch):
    cfg = {"value": "MODEL=synthetic\n"}
    monkeypatch.setattr(
        gate.profile, "CONFIG", SimpleNamespace(
            read_text=lambda **_: cfg["value"]
        )
    )
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(gate.profile, "preflight", lambda _: None)
    changed = []
    def switch(mode):
        changed.append(mode)
        cfg["value"] = gate.profile.updated_config(cfg["value"], mode)
    monkeypatch.setattr(gate.profile, "switch_profile", switch)
    def fake_probe(mode, *_):
        if mode == "hybrid":
            raise RuntimeError("simulated GPU failure")
        return {"profile": mode, "passed": True}
    monkeypatch.setattr(gate, "test_profile", fake_probe)
    with pytest.raises(RuntimeError, match="simulated GPU failure"):
        gate.validate(4000, 20)
    assert changed == ["dflash", "hybrid", "default"]
    assert cfg["value"] == "MODEL=synthetic\n"


def test_validate_returns_passfail_without_output_text(monkeypatch):
    cfg = {"value": "MODEL=synthetic\n"}
    monkeypatch.setattr(
        gate.profile, "CONFIG", SimpleNamespace(
            read_text=lambda **_: cfg["value"]
        )
    )
    monkeypatch.setattr(gate.profile, "ensure_idle", lambda: None)
    monkeypatch.setattr(gate.profile, "preflight", lambda _: None)
    def switch(mode):
        cfg["value"] = gate.profile.updated_config(cfg["value"], mode)
    monkeypatch.setattr(gate.profile, "switch_profile", switch)
    monkeypatch.setattr(
        gate, "test_profile",
        lambda mode, *_: {"profile": mode, "passed": mode == "dflash"},
    )
    result = gate.validate(4000, 20)
    assert result["passed"] is False
    assert result["starting_profile_restored"] == "default"
    assert cfg["value"] == "MODEL=synthetic\n"
    assert "MONDFALTER" not in json.dumps(result)
