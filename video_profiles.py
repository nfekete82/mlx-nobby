"""Server-only configuration for optional LTX-MLX request adapters."""
from __future__ import annotations

import math
import os
from pathlib import Path


def validate_profile(profile):
    if profile not in ("standard", "uncensored"):
        raise ValueError("Video profile muss standard oder uncensored sein")
    return profile


def request_loras(profile="standard"):
    validate_profile(profile)
    if profile == "standard":
        return []
    configured = os.environ.get("LTX_MLX_UNCENSORED_LORA", "").strip()
    if not configured:
        raise ValueError("uncensored: LTX_MLX_UNCENSORED_LORA ist nicht konfiguriert")
    try:
        strength = float(os.environ.get("LTX_MLX_UNCENSORED_LORA_STRENGTH", "1.0"))
        if not math.isfinite(strength):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("uncensored: LTX_MLX_UNCENSORED_LORA_STRENGTH muss eine endliche Zahl sein") from exc
    try:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise OSError
        with path.open("rb"):
            pass
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("uncensored: LTX_MLX_UNCENSORED_LORA muss eine lesbare Adapterdatei sein") from exc
    return [(str(path), strength)]


def prepare_uncensored_loras(loras):
    if not loras:
        return
    try:
        import mlx.core as mx

        for path, _strength in loras:
            # Use the same adapter loader as pinned upstream BlockLoraSource,
            # before any model weights or generation are started.
            mx.load(path)
    except Exception as exc:
        raise ValueError("uncensored: Adapter konnte nicht vorbereitet werden") from exc


if __name__ == "__main__":
    prepare_uncensored_loras(request_loras("uncensored"))
