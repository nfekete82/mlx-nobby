"""CPU-only contract checks for the bounded hybrid soak. No MLX hardware needed."""
import ast
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "validate-hybrid-soak.py"


def test_source_compiles():
    ast.parse(SOURCE.read_text(encoding="utf-8"))


def test_alternating_order_is_counterbalanced():
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "order_for_round")
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    assert namespace["order_for_round"](0) == ("dflash", "hybrid")
    assert namespace["order_for_round"](1) == ("hybrid", "dflash")
    assert namespace["order_for_round"](2) == ("dflash", "hybrid")


def test_preflight_and_rollback_contracts():
    source = SOURCE.read_text(encoding="utf-8")
    assert 'if initial != "default":' in source
    assert 'profile.preflight("dflash")' in source
    assert "profile.ensure_idle()" in source
    assert "finally:" in source
    assert "profile.switch_profile(initial)" in source
    assert "signal.SIGTERM" in source
    assert 'with args.output.open("x", encoding="utf-8")' in source


def test_no_user_content_in_report():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    summarize = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "summarize")
    names = {n.value for n in ast.walk(summarize) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "answer" not in names
    assert "prompt" not in names
    assert "generated_text" not in names
