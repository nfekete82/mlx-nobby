import importlib.util
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def causal():
    file = ROOT / "scripts/benchmark-chat-cache-causal.py"
    spec = importlib.util.spec_from_file_location("slot_causal", file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_causal_slot_cases_and_private_control():
    m = causal()
    assert [c[0] for c in m.SLOT_CASES] == [
        "baseline1", "baseline2", "split2", "early2"]
    assert [c[-1] for c in m.SLOT_CASES] == ["1", "2", "2", "2"]
    assert m.SLOT_CASES[-1][1:3] == ("1", "1")


def test_slot_report_is_numeric_and_correct():
    m = causal()
    rows = []
    for name, slots, hits, matched in [
        ("baseline1", 1, 0, 0),
        ("baseline2", 2, 1, 324),
        ("split2", 2, 1, 324),
        ("early2", 2, 1, 826),
    ]:
        rows.append({"mode": name, "exact_cache_slots": slots, "turns": [
            {"answer_chars": 1300, "delta_exact_hits": 0, "delta_exact_stores": 1},
            {"delta_exact_stores": 2, "delta_matched_tokens": 324},
            {"delta_exact_hits": hits, "delta_matched_tokens": matched,
             "delta_exact_stores": 2, "first_content_ms": 1500},
        ]})
    summary = m.compare_slot_rows(rows)
    assert summary["early2"]["turn3_matched_tokens"] == 826
    assert summary["baseline1"]["turn3_hits"] == 0
    assert summary["split2"]["slots"] == 2
    assert "answer" not in json.dumps(summary).lower()


def test_slot_mode_requires_launcher_compatibility():
    script = (ROOT / "scripts/mlx-server-start").read_text()
    assert 'NOBBY_HYBRID_EXACT_CACHE_ENTRIES:-1' in script
    assert 'export APC_EXACT_CACHE_ENTRIES="$local_hybrid_slots"' in script
    assert '1|2) ;;' in script
    runtime = (ROOT / "scripts/hybrid_apc_dflash_runtime.py").read_text()
    assert "HYBRID_APC_LRU phase=early" in runtime
    assert "HYBRID_APC_LRU phase=final" in runtime
    assert "stored=hybrid_final_saved" in runtime


def test_slot_answer_comparison_returns_only_metadata(tmp_path):
    m = causal()
    rows = []
    for mode, first_answer in [
        ("baseline1", "foo first"),
        ("baseline2", "foo first"),
        ("split2", "bar first"),
        ("early2", "bar first"),
    ]:
        p = tmp_path / f"{mode}.json"
        p.write_text(json.dumps({"answers": [
            {"turn": i, "question": f"question{i}",
             "answer": first_answer if i == 1 else "other"} for i in (1, 2, 3)]}))
        rows.append({"mode": mode, "answers_file": str(p)})
    result = m.compare_slot_answers(rows)
    assert result["baseline1_vs_baseline2"]["turn1_exact_equal"] is True
    assert result["split2_vs_early2"]["turn1_exact_equal"] is True
    assert result["baseline1_vs_early2"]["turn1_exact_equal"] is False
    assert "foo first" not in json.dumps(result)
