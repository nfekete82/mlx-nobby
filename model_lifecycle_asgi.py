"""Opt-in MLX-VLM ASGI entrypoint.

For isolated testing only. No automatic unload and no production activation.
"""

from mlx_vlm.server.app import app as mlx_app

from model_asgi_barrier import ASGIModelBarrier

app = ASGIModelBarrier(mlx_app)
