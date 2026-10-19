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


def test_hits_and_low_swap_alone_cannot_authorize_release():
    rows = [fake("off", 0, 0.2), fake("on", 1, 0.3)] * 3
    result = load().evaluate({"runs": rows})
    assert result["status"] == "REVIEW"
    assert "response_parity_unverified" in result["issues"]
    assert result["on_hit_rate"] == 1
    assert result["swap_delta_gb"] < 1


def complete_report():
    rows = []
    for mode in ("off", "on") * 3:
        row = fake(mode, int(mode == "on"), 0.3)
        row["memory_before_run"] = {"swap_used_gb": 0.3}
        row["turns"] = [
            {"request_sha256": "prompt" + str(i), "answer_sha256": "answer" + str(i),
             "delta_exact_hits": int(i > 0 and mode == "on"),
             "first_content_ms": 1000 if mode == "off" else 800}
            for i in range(3)
        ]
        rows.append(row)
    return {"runs": rows, "release_evidence": {
        key: True for key in ("backend_prompt_equality", "same_model_and_compute_config",
                              "long_session_memory", "rag_and_trust_boundary_review")}}


def test_requires_parity_prompts_memory_and_repeatable_speedup():
    assert load().evaluate(complete_report())["status"] == "PASS"
    cases = (
        ("request_sha256", "changed", "client_prompt_equality_unverified"),
        ("answer_sha256", "changed", "response_parity_unverified"),
        ("first_content_ms", 1100, "repeatable_latency_improvement_unverified"),
    )
    for key, value, issue in cases:
        report = complete_report()
        report["runs"][1]["turns"][2][key] = value
        result = load().evaluate(report)
        assert result["status"] == "REVIEW"
        assert issue in result["issues"]


def test_nonfinite_memory_and_within_run_growth_block_release():
    report = complete_report()
    report["runs"][1]["memory_after_run"]["swap_used_gb"] = float("nan")
    assert load().evaluate(report)["status"] == "REVIEW"
    report = complete_report()
    report["runs"][1]["memory_before_run"]["swap_used_gb"] = 0
    report["runs"][1]["memory_after_run"]["swap_used_gb"] = 2
    assert "within_run_swap_increase_above_limit" in load().evaluate(report)["issues"]


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
