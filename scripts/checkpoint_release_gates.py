"""Conservative gates for the early-checkpoint A/B soak report."""
from __future__ import annotations
import statistics
import math


def evaluate(report, *, min_runs=3, min_hit_rate=0.8, max_swap_increase_gb=1.0):
    runs = report.get("runs") or []
    off = [r for r in runs if r.get("mode") == "off"]
    on = [r for r in runs if r.get("mode") == "on"]
    issues = []
    if len(off) < min_runs or len(on) < min_runs:
        issues.append("insufficient_runs")
    if len(off) != len(on):
        issues.append("unbalanced_runs")
    def turn3(r):
        turns = r.get("turns") or []
        return turns[2] if len(turns) >= 3 else {}
    for mode, group in (("off", off), ("on", on)):
        if any(not turn3(r) for r in group):
            issues.append(f"{mode}_missing_turns")
    hits = sum(turn3(r).get("delta_exact_hits", 0) > 0 for r in on)
    rate = hits / len(on) if on else 0
    if rate < min_hit_rate:
        issues.append("on_hit_rate_below_threshold")
    swap_off = [r.get("memory_after_run", {}).get("swap_used_gb") for r in off]
    swap_on = [r.get("memory_after_run", {}).get("swap_used_gb") for r in on]
    valid = lambda a: bool(a) and all(
        type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in a
    )
    swap_delta = None
    if valid(swap_off) and valid(swap_on):
        swap_delta = statistics.median(swap_on) - statistics.median(swap_off)
        if swap_delta > max_swap_increase_gb:
            issues.append("swap_increase_above_limit")
    else:
        issues.append("memory_metrics_unavailable")
    # Hit rate and swap alone are only telemetry, never release approval.
    pairs = list(zip(off, on))
    speedups = []
    for baseline, candidate in pairs:
        a, b = baseline.get("turns") or [], candidate.get("turns") or []
        if len(a) != 3 or len(b) != 3:
            continue
        if any(not x.get("request_sha256") or
               x["request_sha256"] != y.get("request_sha256")
               for x, y in zip(a, b)):
            issues.append("client_prompt_equality_unverified")
        if any(not x.get("answer_sha256") or
               x["answer_sha256"] != y.get("answer_sha256")
               for x, y in zip(a, b)):
            issues.append("response_parity_unverified")
        if a[0].get("delta_exact_hits") != 0 or b[0].get("delta_exact_hits") != 0:
            issues.append("first_turn_not_cold")
        before, after = a[2].get("first_content_ms"), b[2].get("first_content_ms")
        if valid([before, after]) and before > 0:
            speedups.append((before - after) / before)
        else:
            issues.append("latency_metrics_unavailable")
        for run in (baseline, candidate):
            start = (run.get("memory_before_run") or {}).get("swap_used_gb")
            end = (run.get("memory_after_run") or {}).get("swap_used_gb")
            if not valid([start, end]):
                issues.append("within_run_memory_unverified")
            elif end - start > max_swap_increase_gb:
                issues.append("within_run_swap_increase_above_limit")
    if len(speedups) < min_runs or any(value <= 0 for value in speedups):
        issues.append("repeatable_latency_improvement_unverified")
    # These require separate hardware/security review, beyond the short probe.
    evidence = report.get("release_evidence") or {}
    for key in ("backend_prompt_equality", "same_model_and_compute_config",
                "long_session_memory", "rag_and_trust_boundary_review"):
        if evidence.get(key) is not True:
            issues.append(key + "_unverified")
    issues = list(dict.fromkeys(issues))
    return {"status": "PASS" if not issues else "REVIEW", "issues": issues,
            "paired_latency_improvement": speedups,
            "on_hit_rate": rate, "swap_delta_gb": swap_delta,
            "off_runs": len(off), "on_runs": len(on)}
