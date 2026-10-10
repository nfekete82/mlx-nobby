"""Model call efficiency reporting from bounded, content-free performance events."""
def model_efficiency(response):
    perf = response.get("performance", {}) if isinstance(response, dict) else {}
    events = perf.get("events", []) if isinstance(perf, dict) else []
    calls = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("action") != "provider.complete":
            continue
        calls.append({key: event[key] for key in (
            "duration_ms", "input_chars", "prompt_tokens", "completion_tokens",
            "total_tokens", "effective_output_tokens_per_s",
            "queue_wait_ms", "model_setup_ms", "upstream_request_ms", "usage_method"
        ) if key in event})
    return {"calls": calls, "call_count": len(calls),
            "known_prompt_tokens": sum(call.get("prompt_tokens", 0) for call in calls),
            "known_completion_tokens": sum(call.get("completion_tokens", 0) for call in calls)}
