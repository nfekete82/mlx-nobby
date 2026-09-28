"""Production speech entrypoint with optional alignment routes."""

from speech.app import FFMPEG, MODEL_NAME, app, get_model
from speech.alignment_routes import install_routes as install_alignment_routes


install_alignment_routes(
    app,
    get_model=get_model,
    ffmpeg=FFMPEG,
    model_name=MODEL_NAME,
)

__all__ = ["app"]
