"""Monotonic image-service timing telemetry does not expose private data."""
from image_job_timings import ImageJobTimings


def test_image_job_timings_breakdown_is_monotonic():
    ticks = iter([100, 101, 103, 110, 112])
    timing = ImageJobTimings(clock=lambda: next(ticks))
    timing.mark("resources_acquired")
    timing.mark("execution_started")
    timing.mark("execution_finished")
    data = timing.report()
    assert data["resource_wait_ms"] == 1000.0
    assert data["preparation_ms"] == 2000.0
    assert data["execution_ms"] == 7000.0
    assert data["finalization_ms"] == 2000.0
    assert data["total_ms"] == 12000.0
    assert "prompt" not in data and "path" not in data


def test_image_job_timings_missing_milestones_return_null():
    ticks = iter([100, 101])
    timing = ImageJobTimings(clock=lambda: next(ticks))
    data = timing.report()
    assert data["total_ms"] == 1000.0
    assert data["resource_wait_ms"] is None
    assert data["execution_ms"] is None


def test_image_job_timings_reject_arbitrary_event_names():
    import pytest
    timing = ImageJobTimings(clock=lambda: 10)
    with pytest.raises(ValueError):
        timing.mark("private_prompt")
