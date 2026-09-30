"""Provider dispatcher for the stable MPS and experimental native-MLX video backends."""
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


def availability(model):
    return mlx.availability(model) if _is_mlx(model) else mps.availability(model)


def generate(model, params, output, **kwargs):
    if _is_mlx(model):
        return mlx.generate(model, params, output, **kwargs)
    return mps.generate(model, params, output, **kwargs)


def unload(runtime):
    if mlx.owns_runtime(runtime):
        return mlx.unload(runtime)
    return mps.unload(runtime)


def warm_runtime_status(model=None):
    if model is not None and _is_mlx(model):
        return {
            "loaded": False,
            "idle_timeout_seconds": 0,
            "backend": "mlx-cli",
        }
    status = dict(mps.warm_runtime_status())
    status["backend"] = "pytorch-mps"
    return status
