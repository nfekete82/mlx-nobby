"""Agent bridge routes for Image Pipeline V2."""

from __future__ import annotations

from fastapi import FastAPI

from agent import image_api


def install_routes(app: FastAPI):
    @app.post("/api/image/prewarm")
    def image_prewarm(request: dict):
        return image_api.request(
            "POST",
            "/prewarm",
            request,
            timeout=15,
        )

    @app.get("/api/image/pipeline")
    def image_pipeline_state():
        return image_api.request(
            "GET",
            "/pipeline",
            timeout=15,
        )
