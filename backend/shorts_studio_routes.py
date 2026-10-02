"""Web-container proxy routes for Shorts Studio."""

import urllib.parse


def _route_exists(app, path, method):
    method = str(method).upper()
    return any(
        getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
        for route in app.routes
    )


def install_routes(app, agent_json_request):
    """Register Shorts Studio proxy routes exactly once."""
    from backend.shorts_draft_routes import install_routes as install_drafts
    install_drafts(app, agent_json_request)

    history_path = "/api/mlx/shorts-jobs"
    if not _route_exists(app, history_path, "GET"):
        @app.get(history_path)
        def shorts_history(limit: int = 50):
            safe_limit = max(1, min(int(limit), 200))
            return agent_json_request(
                "GET",
                f"/api/shorts-jobs?limit={safe_limit}",
                None,
                timeout=15,
            )

    failed_cleanup_path = "/api/mlx/shorts-jobs/failed"
    if not _route_exists(app, failed_cleanup_path, "DELETE"):
        @app.delete(failed_cleanup_path)
        def delete_failed_shorts():
            return agent_json_request(
                "DELETE",
                "/api/shorts-jobs/failed",
                None,
                timeout=30,
            )

    delete_path = "/api/mlx/shorts-jobs/{job_id}"
    if not _route_exists(app, delete_path + '/retry', 'POST'):
        @app.post('/api/mlx/shorts-jobs/{job_id}/retry', status_code=202)
        def retry(job_id: str):
            return agent_json_request('POST', f'/api/shorts-jobs/{urllib.parse.quote(job_id, safe="")}/retry', {}, timeout=60)
    if not _route_exists(app, delete_path, "DELETE"):
        @app.delete(delete_path)
        def delete_short(job_id: str):
            safe_job = urllib.parse.quote(job_id, safe="")
            return agent_json_request(
                "DELETE",
                f"/api/shorts-jobs/{safe_job}",
                None,
                timeout=30,
            )

    revision_path = "/api/mlx/shorts-jobs/{job_id}/scenes/{scene_id}/revise"
    if not _route_exists(app, revision_path, "POST"):
        @app.post(revision_path, status_code=202)
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
