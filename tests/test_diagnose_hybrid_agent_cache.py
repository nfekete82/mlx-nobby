import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "diagnose-hybrid-agent-cache.py"


def test_diagnostic_parses():
    ast.parse(SOURCE.read_text(encoding="utf-8"))


def test_no_profile_switch_and_no_user_data():
    source = SOURCE.read_text(encoding="utf-8")
    assert "profiles.switch_profile(" not in source
    assert "profiles.ensure_idle()" in source
    assert "bench.synthetic_context(" in source
    assert '"content": answer' in source
    assert 'if timing["output_characters"] > len(answer):' in source


def test_cache_deltas_guard_against_reset():
    source = SOURCE.read_text(encoding="utf-8")
    assert "b >= a" in source
    assert 'current = after' in source
    assert 'followup_exact_hits' in source


def test_telemetry_output_private():
    source = SOURCE.read_text(encoding="utf-8")
    assert "os.O_EXCL" in source
    assert "0o600" in source
    assert '"cache_delta": change' in source
    assert '"raw_output"' not in source
