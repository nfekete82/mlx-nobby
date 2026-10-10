"""Model telemetry carries phase timings without leaking prompt content."""
from agent.model_provider import ModelResponse
from agent.model_efficiency import model_efficiency


def test_response_telemetry_default_is_independent():
    a = ModelResponse(text="a", model="m", role="agent", usage={})
    b = ModelResponse(text="b", model="m", role="agent", usage={})
    a.telemetry["queue_wait_ms"] = 42
    assert b.telemetry == {}


def test_phase_timings_survive_summary():
    response = {"performance": {"events": [{
        "phase": "model", "action": "provider.complete",
        "duration_ms": 1000, "queue_wait_ms": 200,
        "model_setup_ms": 100, "upstream_request_ms": 700,
        "usage_method": "estimate", "input_chars": 1200,
        "prompt_content": "must never appear"
    }]}}
    result = model_efficiency(response)["calls"][0]
    assert result["queue_wait_ms"] == 200
    assert result["model_setup_ms"] == 100
    assert result["upstream_request_ms"] == 700
    assert result["usage_method"] == "estimate"
    assert "prompt_content" not in result
