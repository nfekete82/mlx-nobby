import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def policy():
    spec = importlib.util.spec_from_file_location("policy", ROOT / "scripts/hybrid_checkpoint_policy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOBBY_HYBRID_EARLY_CHECKPOINT", raising=False)
    assert policy().early_checkpoint(1073, 0, 128) is None


def test_secondary_checkpoint_on_observed_pattern(monkeypatch):
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT", "1")
    assert policy().early_checkpoint(1073, 324, 128) == 913
    assert policy().early_checkpoint(324, 0, 200) is None
    assert policy().early_checkpoint(1073, 950, 128) is None


def test_runtime_stores_early_at_actual_prefill_boundary():
    spec = importlib.util.spec_from_file_location(
        "runtime", ROOT / "scripts/hybrid_apc_dflash_runtime.py")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    text = runtime.PREFILL_ADAPTER
    assert "hybrid_early_boundary - hybrid_consumed" in text
    assert "hybrid_full_ids[:hybrid_early_boundary]" in text
    assert text.index("hybrid_full_ids[:hybrid_early_boundary]") < text.index(
        "hybrid_full_ids[:hybrid_checkpoint]")
