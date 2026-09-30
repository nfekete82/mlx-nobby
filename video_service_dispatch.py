"""Runtime wiring for pluggable LTX video backends.

`video_service` remains the stable service implementation.  This entrypoint
rebinds its provider hooks before FastAPI starts so the existing MPS backend and
the experimental native-MLX backend can coexist without duplicating service
logic.
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
    unload,
    validate_first_frame,
)


service.ProviderCancelled = ProviderCancelled
service.availability = availability
service.generate = generate
service.i2v_aspect_ratio = i2v_aspect_ratio
service.i2v_source_size = i2v_source_size
service.i2v_target_size = i2v_target_size
service.unload = unload
service.validate_first_frame = validate_first_frame

app = service.app

__all__ = ["app"]
