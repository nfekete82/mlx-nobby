"""Summarize agent performance events without recording source contents."""
from collections import defaultdict


def summarize_performance(response):
    performance = response.get("performance") if isinstance(response, dict) else None
    events = performance.get("events") if isinstance(performance, dict) else None
    if not isinstance(events, list):
        return {"available": False, "events": 0, "by_action_ms": {}}
    groups = defaultdict(list)
    for item in events:
        if not isinstance(item, dict):
            continue
        duration = item.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            continue
        key = str(item.get("phase") or "unknown") + ":" + str(item.get("action") or "unknown")
        groups[key].append(float(duration))
    return {
        "available": True,
        "events": sum(map(len, groups.values())),
        "by_action_ms": {
            key: {"calls": len(values), "total": round(sum(values), 2),
                  "mean": round(sum(values) / len(values), 2)}
            for key, values in sorted(groups.items())
        },
    }
