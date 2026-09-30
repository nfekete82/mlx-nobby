"""Web routes for Image Pipeline V2 prewarm and observability."""

from __future__ import annotations

from fastapi import FastAPI


def install_routes(app: FastAPI, agent_json_request):
    @app.post("/api/image/prewarm")
    def image_prewarm(request: dict):
        return agent_json_request(
            "POST",
            "/api/image/prewarm",
            request,
            timeout=15,
        )

    @app.get("/api/image/pipeline")
    def image_pipeline_state():
        return agent_json_request(
            "GET",
            "/api/image/pipeline",
            timeout=15,
        )
