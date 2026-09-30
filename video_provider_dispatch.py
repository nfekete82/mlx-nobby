"""Provider dispatcher for the stable MPS and native-MLX video backends."""
from __future__ import annotations

import video_providers as mps
import video_providers_mlx as mlx


ProviderCancelled = mps.ProviderCancelled
validate_first_frame = mps.validate_first_frame
i2v_source_size = mps.i2v_source_size
i2v_aspect_ratio = mps.i2v_aspect_ratio
i2v_target_size = mps.i2v_target_size


def _is_mlx(model):
    return str(model.get("provider") or "") == "ltx-mlx"


def _mlx_progress_event(params, event):
    """Restore cumulative MLX step metadata from the worker progress value.

    The persistent worker maps completed denoising steps onto 0..90% and keeps
    the remaining 10% for decode/mux.  The provider currently forwards that
    progress value but not the worker's current_step/total_steps fields.  Keep
    the service contract exact until those fields are forwarded natively.
    """
    enriched = dict(event or {})
    if enriched.get("step") is not None and enriched.get("total_steps") is not None:
        return enriched

    phase = str(enriched.get("phase") or "").lower()
    progress = enriched.get("progress")
    if phase != "denoising" or not isinstance(progress, (int, float)) or isinstance(progress, bool):
        return enriched

    value = float(progress)
    if value > 1:
        value /= 100
    if value <= 0 or value > 0.9:
        return enriched

    try:
        total_steps = int(params.get("steps") or (2 if params.get("quality") == "preview" else 11))
    except (TypeError, ValueError):
        total_steps = 2 if params.get("quality") == "preview" else 11
    if total_steps <= 0:
        return enriched

    current_step = int(round(value * total_steps / 0.9))
    if 1 <= current_step <= total_steps:
        enriched["step"] = current_step
        enriched["total_steps"] = total_steps
    return enriched


def availability(model):
    return mlx.availability(model) if _is_mlx(model) else mps.availability(model)


def generate(model, params, output, **kwargs):
    if _is_mlx(model):
        callback = kwargs.get("progress_callback")
        if callback is not None:
            def progress_callback(event):
                callback(_mlx_progress_event(params, event))

            kwargs = dict(kwargs)
            kwargs["progress_callback"] = progress_callback
        return mlx.generate(model, params, output, **kwargs)
    return mps.generate(model, params, output, **kwargs)


def unload(runtime):
    if mlx.owns_runtime(runtime):
        return mlx.unload(runtime)
    return mps.unload(runtime)


def warm_runtime_status(model=None):
    if model is not None:
        if _is_mlx(model):
            return dict(mlx.warm_runtime_status())
        status = dict(mps.warm_runtime_status())
        status["backend"] = "pytorch-mps"
        return status

    mlx_status = dict(mlx.warm_runtime_status())
    if mlx_status.get("loaded"):
        return mlx_status
    mps_status = dict(mps.warm_runtime_status())
    mps_status["backend"] = "pytorch-mps"
    if mps_status.get("loaded"):
        return mps_status
    return {
        "loaded": False,
        "idle_timeout_seconds": max(
            float(mlx_status.get("idle_timeout_seconds") or 0),
            float(mps_status.get("idle_timeout_seconds") or 0),
        ),
        "backend": "none",
        "model": None,
    }
