"""Runtime wiring for pluggable LTX video backends.

`video_service` remains the stable service implementation. This entrypoint
rebinds its provider hooks before FastAPI starts so the existing MPS backend and
the native-MLX backend can coexist without duplicating service logic.
"""
from __future__ import annotations

import video_service as service
from video_provider_dispatch import (
    ProviderCancelled,
    availability,
    generate,
    i2v_aspect_ratio,
    i2v_source_size,
    i2v_target_size,
    reset_mlx_warm_runtime,
    unload,
    validate_first_frame,
)


def _job_total_steps(payload):
    """Use the validated profile step count for public job progress."""
    try:
        steps = int(payload.steps)
    except (TypeError, ValueError):
        steps = 0
    if steps > 0:
        return steps
    return 2 if payload.quality == "preview" else 11


service.ProviderCancelled = ProviderCancelled
service.availability = availability
service.generate = generate
service.i2v_aspect_ratio = i2v_aspect_ratio
service.i2v_source_size = i2v_source_size
service.i2v_target_size = i2v_target_size
service.unload = unload
service.validate_first_frame = validate_first_frame
service._job_total_steps = _job_total_steps

app = service.app


@app.post("/runtime/mlx/reset")
def reset_mlx_runtime():
    """Force the idle MLX worker cold without restarting the video service."""
    with service._jobs_lock:
        active_job = next((
            job.get("id")
            for job in service._jobs.values()
            if job.get("status") in service.ACTIVE
        ), None)
    if active_job:
        raise service.HTTPException(
            409,
            f"MLX-Runtime kann während Video-Job {active_job} nicht zurückgesetzt werden",
        )
    before = reset_mlx_warm_runtime()
    return {
        "ok": True,
        "backend": "mlx-worker",
        "was_loaded": bool(before.get("loaded")),
        "requests_completed": int(before.get("requests_completed") or 0),
    }


__all__ = ["app"]
