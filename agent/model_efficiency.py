"""Model call efficiency reporting from bounded, content-free performance events."""
import math

CALL_PURPOSES = frozenset({"agent.call", "agent.plan", "agent.plan_repair",
    "agent.extract", "agent.verify",
    "agent.final", "agent.final_repair", "agent.evidence_repair",
    "agent.coding_readonly_final", "agent.subagent_report", "unknown"})


def model_efficiency(response):
    perf = response.get("performance", {}) if isinstance(response, dict) else {}
    events = perf.get("events", []) if isinstance(perf, dict) else []
    calls = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("action") != "provider.complete":
            continue
        call = {key: event[key] for key in (
            "duration_ms", "input_chars", "prompt_tokens", "completion_tokens",
            "total_tokens", "effective_output_tokens_per_s",
            "queue_wait_ms", "lease_wait_ms", "lock_wait_ms", "observed_holder_age_ms", "model_setup_ms", "upstream_request_ms"
        ) if type(event.get(key)) in (int, float) and math.isfinite(event[key]) and event[key] >= 0}
        if isinstance(event.get("purpose"), str) and event["purpose"] in CALL_PURPOSES:
            call["purpose"] = event["purpose"]
        if isinstance(event.get("observed_holder_role"), str) and event["observed_holder_role"] in {"agent", "chat", "coding", "image", "video", "embedding", "speech-stt", "speech-tts", "speech-tts-clone", "router", "vision-classifier", "image-upscale", "other", "unknown", "none", "possible_agent_holder"}:
            call["observed_holder_role"] = event["observed_holder_role"]
        if isinstance(event.get("usage_method"), str) and event["usage_method"] in {"upstream", "estimate"}:
            call["usage_method"] = event["usage_method"]
        calls.append(call)
    return {"calls": calls, "call_count": len(calls),
            "known_prompt_tokens": sum(call.get("prompt_tokens", 0) for call in calls),
            "known_completion_tokens": sum(call.get("completion_tokens", 0) for call in calls)}
