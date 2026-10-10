"""Regression tests for lease owner classification without changing locks."""
from unittest.mock import patch
from agent.model_provider import MLXProvider, ModelRequest, ModelResponse
from contextlib import nullcontext


def test_no_wait_does_not_claim_unknown_owner():
    provider = MLXProvider(
        runtime_lock=nullcontext(),
        runtime_lease=lambda context: nullcontext(),
        ensure_model_for_role=lambda role: {"resolved": {"repo": "mock"}},
        load_config=lambda: {"PORT": 8000},
    )
    fake = ModelResponse(text="done", model="mock", role="agent", usage={})
    with patch.object(provider, "_complete", return_value=fake), \
         patch("agent.model_provider._with_memory", side_effect=lambda r, c: r), \
         patch("agent.model_provider._with_system_clock", side_effect=lambda r: r):
        actual = provider.complete(ModelRequest(messages=[]))
    assert actual.telemetry["observed_holder_role"] == "none"
    assert actual.telemetry["lease_wait_ms"] < 100
