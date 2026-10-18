import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location("native_checkpoint_test_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_native_checkpoint_is_existing_chunk_boundary(monkeypatch):
    policy = load(ROOT / "scripts/hybrid_checkpoint_policy.py")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT", "1")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE", "1")

    assert policy.early_checkpoint(986, 324, 16, prefill_step_size=256) == 580
    assert policy.early_checkpoint(986, 324, 16, prefill_step_size=64) == 772
    assert policy.early_checkpoint(324, 0, 16, prefill_step_size=256) is None

    for step in (16, 32, 64, 128, 256, 512):
        boundary = policy.early_checkpoint(986, 324, 16, prefill_step_size=step)
        if boundary is not None:
            assert (boundary - 324) % step == 0
            assert 324 < boundary <= 826

    # No inferred step size: never force an arbitrary extra inference call.
    assert policy.early_checkpoint(986, 324, 16) is None
    assert policy.early_checkpoint(986, 324, 16, prefill_step_size=0) is None


def test_existing_forced_boundary_unchanged_when_not_aligned(monkeypatch):
    policy = load(ROOT / "scripts/hybrid_checkpoint_policy.py")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT", "1")
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE", "0")
    assert policy.early_checkpoint(986, 324, 16, prefill_step_size=256) == 826
    monkeypatch.delenv("NOBBY_HYBRID_EARLY_CHECKPOINT", raising=False)
    monkeypatch.setenv("NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE", "1")
    assert policy.early_checkpoint(986, 324, 16, prefill_step_size=256) is None


def test_four_arm_native_replay_summary():
    causal = load(ROOT / "scripts/benchmark-chat-cache-causal.py")
    assert [case[0] for case in causal.NATIVE_CASES] == [
        "baseline1", "baseline2", "early2", "native2"
    ]
    assert causal.NATIVE_CASES[-1] == ("native2", "1", "1", "2", "1")
    rows = []
    for mode, hit, matched in (
        ("baseline1", 0, 0),
        ("baseline2", 1, 324),
        ("early2", 1, 826),
        ("native2", 1, 580),
    ):
        rows.append({"mode": mode, "exact_cache_slots": 1 if mode == "baseline1" else 2,
                     "turns": [
                         {"answer_chars": 1000, "delta_exact_hits": 0, "delta_exact_stores": 1},
                         {"delta_matched_tokens": 324, "delta_exact_stores": 1},
                         {"delta_exact_hits": hit, "delta_matched_tokens": matched,
                          "first_content_ms": 1700, "total_ms": 18000,
                          "delta_exact_stores": 2},
                     ]})
    result = causal.compare_native_rows(rows)
    assert result["native2"]["turn3_matched_tokens"] == 580
    assert result["baseline2"]["turn3_matched_tokens"] == 324
    assert result["early2"]["turn3_matched_tokens"] == 826


def test_native_answer_review_does_not_expose_text(tmp_path):
    causal = load(ROOT / "scripts/benchmark-chat-cache-causal.py")
    rows = []
    for mode, reply in (
        ("baseline1", "Baseline private reply"),
        ("baseline2", "Baseline private reply"),
        ("early2", "Different private reply"),
        ("native2", "Baseline private reply"),
    ):
        path = tmp_path / (mode + ".json")
        path.write_text(json.dumps({"answers": [
            {"turn": i, "question": f"Question {i}", "answer": reply}
            for i in (1, 2, 3)]}), encoding="utf-8")
        rows.append({"mode": mode, "answers_file": str(path)})
    result = causal.compare_native_answers(rows)
    assert result["baseline1_vs_native2"]["turn1_exact_equal"] is True
    assert result["baseline1_vs_early2"]["turn1_exact_equal"] is False
    assert "private" not in json.dumps(result)


def test_adapter_consumes_real_prefill_step_size():
    adapter = (ROOT / "scripts/hybrid_apc_dflash_runtime.py").read_text(encoding="utf-8")
    assert "prefill_step_size=prefill_step_size" in adapter
    assert "hybrid_early_boundary - hybrid_consumed" in adapter
