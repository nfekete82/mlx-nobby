"""Conservative gates for the early-checkpoint A/B soak report."""
from __future__ import annotations
import statistics


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
    valid = lambda a: a and all(isinstance(v, (int, float)) for v in a)
    swap_delta = None
    if valid(swap_off) and valid(swap_on):
        swap_delta = statistics.median(swap_on) - statistics.median(swap_off)
        if swap_delta > max_swap_increase_gb:
            issues.append("swap_increase_above_limit")
    else:
        issues.append("memory_metrics_unavailable")
    return {"status": "PASS" if not issues else "REVIEW", "issues": issues,
            "on_hit_rate": rate, "swap_delta_gb": swap_delta,
            "off_runs": len(off), "on_runs": len(on)}
