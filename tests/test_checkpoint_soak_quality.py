import importlib.util
from pathlib import Path


def mod():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark-chat-cache-ab.py"
    spec = importlib.util.spec_from_file_location("ab_soak", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_swap_delta():
    m = mod()
    assert m.swap_difference({"swap_used_gb": 1.0}, {"swap_used_gb": 1.3}) == 0.3
    assert m.swap_difference({}, {"swap_used_gb": 1.3}) is None


def test_soak_mode_preserves_original_sequence():
    assert mod().sequence(5) == ["off", "on"] * 5
