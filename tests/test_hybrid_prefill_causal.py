import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / "scripts/benchmark-chat-cache-causal.py"
    spec = importlib.util.spec_from_file_location("hybrid_causal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_causal_modes_and_summary():
    m = module()
    assert [case[0] for case in m.CASES] == ["off", "split_only", "on"]
    rows = []
    for name, hits, matched, chars in [
        ("off", 0, 0, 1805),
        ("split_only", 0, 0, 1370),
        ("on", 1, 725, 1370),
    ]:
        rows.append({"mode": name, "turns": [
            {"answer_chars": chars, "delta_exact_hits": 0},
            {},
            {"delta_exact_hits": hits, "delta_matched_tokens": matched},
        ]})
    summary = m.compare_case_rows(rows)
    assert summary["split_only"]["first_turn_exact_hits"] == 0
    assert summary["on"]["third_turn_matched_tokens"] == 725


def test_compare_first_turn_content_without_leaking_text(tmp_path):
    m = module()
    rows = []
    for mode, content in [
        ("off", "One full answer"),
        ("split_only", "Short"),
        ("on", "Short"),
    ]:
        path = tmp_path / (mode + ".json")
        path.write_text(json.dumps({"answers": [
            {"turn": n, "question": "q" + str(n),
             "answer": content if n == 1 else "response"}
            for n in (1, 2, 3)]}))
        rows.append({"mode": mode, "answers_file": str(path)})
    result = m.compare_answers(rows)
    assert result["off_vs_split_only"]["first_turn_exact_equal"] is False
    assert result["split_only_vs_on"]["first_turn_exact_equal"] is True
    assert "One full answer" not in json.dumps(result)


def test_runtime_keeps_split_boundary_without_store():
    source = (ROOT / "scripts/hybrid_apc_dflash_runtime.py").read_text()
    assert 'NOBBY_HYBRID_EARLY_CHECKPOINT_STORE' in source
    assert 'Hybrid early checkpoint split-only' in source
    assert source.index('if hybrid_early_boundary is not None and hybrid_consumed == hybrid_early_boundary:') < source.index('NOBBY_HYBRID_EARLY_CHECKPOINT_STORE')
