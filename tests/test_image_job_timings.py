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


def test_sdxl_native_phases_partition_execution_without_double_counting():
    # Native execution runs through preparation, provider, WebP finalizing,
    # SDXL teardown and coordinator/chat restoration, in this order.
    ticks = iter([100, 101, 102, 103, 115, 116, 118, 122, 124])
    timing = ImageJobTimings(clock=lambda: next(ticks))
    for phase in (
        "resources_acquired", "execution_started", "prepared",
        "provider_done", "result_ready", "sdxl_released", "execution_finished",
    ):
        timing.mark(phase)
    data = timing.report()
    assert data["execution_ms"] == 20000.0
    assert data["render_setup_ms"] == 1000.0
    assert data["provider_and_setup_ms"] == 12000.0
    assert data["output_finalize_ms"] == 1000.0
    assert data["sdxl_unload_ms"] == 2000.0
    assert data["runtime_return_ms"] == 4000.0
    assert sum(data[key] for key in (
        "render_setup_ms", "provider_and_setup_ms", "output_finalize_ms",
        "sdxl_unload_ms", "runtime_return_ms",
    )) == data["execution_ms"]
    assert "source_path" not in str(data) and "user_prompt" not in str(data)


def test_non_sdxl_native_runtime_return_starts_after_artifact_ready():
    ticks = iter([100, 101, 102, 103, 108, 109, 111, 112])
    timing = ImageJobTimings(clock=lambda: next(ticks))
    for phase in (
        "resources_acquired", "execution_started", "prepared",
        "provider_done", "result_ready", "execution_finished",
    ):
        timing.mark(phase)
    data = timing.report()
    assert data["sdxl_unload_ms"] is None
    assert data["runtime_return_ms"] == 2000.0
    assert data["execution_ms"] == 9000.0


def test_failed_job_keeps_missing_stages_null():
    ticks = iter([100, 101, 102, 105])
    timing = ImageJobTimings(clock=lambda: next(ticks))
    timing.mark("resources_acquired")
    timing.mark("execution_started")
    report = timing.report()
    assert report["render_setup_ms"] is None
    assert report["output_finalize_ms"] is None
    assert report["runtime_return_ms"] is None
