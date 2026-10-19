import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / "scripts/benchmark-chat-cache-causal.py"
    spec = importlib.util.spec_from_file_location("hybrid_prefix_gap", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample_diag(*, checkpoint, common, matched=0, sem=True, reason="prefix_shorter_than_checkpoint"):
    return (f"reason={reason} prompt_tokens=1700 checkpoint_tokens={checkpoint} "
            f"matched_tokens={matched} common_prefix_tokens={common} "
            f"previous_tokens=1060 semantic_hash_same={sem} stored=False")


def test_parse_numeric_diagnostic_without_token_contents():
    mod = module()
    value = mod.parse_lookup_diagnostic(sample_diag(checkpoint=1000, common=835))
    assert value["reason"] == "prefix_shorter_than_checkpoint"
    assert value["common_prefix_tokens"] == 835
    assert value["semantic_hash_same"] is True
    assert mod.parse_lookup_diagnostic(None) is None
    assert mod.parse_lookup_diagnostic("reason=unknown") is None


def test_prefix_gap_predicts_extra_checkpoint_too_late():
    mod = module()
    cases = []
    for mode in ("off", "split_only", "on"):
        cases.append({
            "mode": mode,
            "turns": [
                {},
                {"hybrid_diagnostic": sample_diag(checkpoint=1057, common=0,
                                                  reason="exact_hit", matched=324)},
                {"hybrid_diagnostic": sample_diag(checkpoint=1700, common=750)},
            ],
        })
    result = mod.prefix_gap_summary(cases)
    assert result["on"]["previous_full_checkpoint_tokens"] == 1057
    assert result["on"]["turn3_common_prefix_tokens"] == 750
    assert result["on"]["turn3_prefix_gap_tokens"] == 307
    assert result["on"]["hypothetical_early_boundary_tokens"] == 897
    assert result["on"]["hypothetical_early_within_common_prefix"] is False


def test_prefix_gap_can_predict_eligible_snapshot_but_not_claim_hit():
    mod = module()
    cases = [{
        "mode": "on",
        "turns": [
            {},
            {"hybrid_diagnostic": sample_diag(checkpoint=1057, common=0,
                                              reason="exact_hit", matched=324)},
            {"hybrid_diagnostic": sample_diag(checkpoint=1700, common=1000,
                                              matched=0)},
        ],
    }]
    result = mod.prefix_gap_summary(cases)["on"]
    assert result["hypothetical_early_within_common_prefix"] is True
    assert result["turn3_actual_matched_tokens"] == 0


def test_diagnostic_is_available_only_when_complete():
    mod = module()
    result = mod.prefix_gap_summary([{"mode": "on", "turns": [{}, {}, {}]}])
    assert result["on"] == {"available": False}
