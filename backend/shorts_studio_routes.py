"""Web-container proxy routes for Shorts Studio."""

import urllib.parse


def install_routes(app, agent_json_request):
    """Register Shorts Studio proxy routes exactly once."""
    route_path = "/api/mlx/shorts-jobs/{job_id}/scenes/{scene_id}/revise"
    if any(getattr(route, "path", None) == route_path for route in app.routes):
        return app

    @app.post(route_path, status_code=202)
    def revise_short_scene(job_id: str, scene_id: str, request: dict):
        safe_job = urllib.parse.quote(job_id, safe="")
        safe_scene = urllib.parse.quote(scene_id, safe="")
        return agent_json_request(
            "POST",
            f"/api/shorts/jobs/{safe_job}/scenes/{safe_scene}/revise",
            request,
            timeout=30,
        )

    return app
