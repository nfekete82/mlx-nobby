import importlib.util
from pathlib import Path


def load():
    path = Path(__file__).resolve().parents[1] / "scripts/checkpoint_release_gates.py"
    spec = importlib.util.spec_from_file_location("checkpoint_gates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake(mode, hit, swap):
    return {
        "mode": mode,
        "turns": [{}, {}, {"delta_exact_hits": hit}],
        "memory_after_run": {"swap_used_gb": swap},
    }


def test_passes_reliable_hits_and_low_swap():
    rows = [fake("off", 0, 0.2), fake("on", 1, 0.3)] * 3
    result = load().evaluate({"runs": rows})
    assert result["status"] == "PASS"
    assert result["on_hit_rate"] == 1
    assert result["swap_delta_gb"] < 1


def test_short_test_does_not_claim_release_ready():
    rows = [fake("off", 0, 0.2), fake("on", 1, 0.3)] * 2
    result = load().evaluate({"runs": rows})
    assert result["status"] == "REVIEW"
    assert "insufficient_runs" in result["issues"]


def test_missing_memory_or_hits_requires_review():
    rows = [fake("off", 0, None), fake("on", 0, None)] * 3
    result = load().evaluate({"runs": rows})
    assert "memory_metrics_unavailable" in result["issues"]
    assert "on_hit_rate_below_threshold" in result["issues"]
