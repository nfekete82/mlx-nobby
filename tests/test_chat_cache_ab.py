import importlib.util
from pathlib import Path
import pytest


def load():
    file = Path(__file__).resolve().parents[1] / "scripts/benchmark-chat-cache-ab.py"
    spec = importlib.util.spec_from_file_location("cache_ab", file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alternates():
    assert load().sequence(3) == ["off", "on", "off", "on", "off", "on"]


def test_summary_per_mode():
    m = load()
    data = [{"mode": "off", "turns": [None, None, {
        "delta_exact_hits": 0, "delta_matched_tokens": 0,
        "first_content_ms": 3000, "total_ms": 20000}]},
        {"mode": "on", "turns": [None, None, {
        "delta_exact_hits": 1, "delta_matched_tokens": 913,
        "first_content_ms": 1500, "total_ms": 17000}]}]
    result = m.summarize(data)
    assert result["off"]["turn3_matched_tokens"] == [0]
    assert result["on"]["turn3_exact_hits"] == [1]
    assert result["on"]["turn3_first_content_ms_median"] == 1500
