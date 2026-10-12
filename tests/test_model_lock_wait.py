"""Verify distinct lease and runtime-lock wait telemetry."""
from contextlib import contextmanager
from unittest.mock import patch
import time

from agent.model_provider import MLXProvider, ModelRequest, ModelResponse


@contextmanager
def slow_lease(_context):
    time.sleep(0.015)
    yield


@contextmanager
def slow_lock():
    time.sleep(0.015)
    yield


def test_lease_and_lock_wait_are_separate():
    provider = MLXProvider(
        runtime_lock=slow_lock(),
        ensure_model_for_role=lambda role: {"resolved": {"repo": "test"}},
        load_config=lambda: {"PORT": 8000},
        runtime_lease=slow_lease,
    )
    fake = ModelResponse(text="ok", model="test", role="agent", usage={})
    with patch.object(provider, "_complete", return_value=fake), \
         patch("agent.model_provider._with_system_clock", side_effect=lambda r: r), \
         patch("agent.model_provider._with_memory", side_effect=lambda r, c: r):
        result = provider.complete(ModelRequest(messages=[]))
    assert result.telemetry["lease_wait_ms"] >= 10
    assert result.telemetry["lock_wait_ms"] >= 10
    assert result.telemetry["queue_wait_ms"] >= (
        result.telemetry["lease_wait_ms"] + result.telemetry["lock_wait_ms"] - 2
    )
