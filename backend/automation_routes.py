"""Web proxy routes for the local automation scheduler."""

from __future__ import annotations

import urllib.parse

from fastapi import FastAPI, Query


def install_routes(app: FastAPI, agent_json_request) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/mlx/automations" not in paths:
        @app.get("/api/mlx/automations")
        def automation_list():
            return agent_json_request("GET", "/api/automations", timeout=15)

        @app.post("/api/mlx/automations", status_code=201)
        def automation_create(request: dict):
            return agent_json_request("POST", "/api/automations", request, timeout=15)

    if "/api/mlx/automations/runs" not in paths:
        @app.get("/api/mlx/automations/runs")
        def automation_runs(
            automation_id: str | None = None,
            limit: int = Query(default=50, ge=1, le=200),
        ):
            query = {"limit": str(limit)}
            if automation_id:
                query["automation_id"] = automation_id
            return agent_json_request(
                "GET",
                "/api/automations/runs?" + urllib.parse.urlencode(query),
                timeout=15,
            )

    if "/api/mlx/automations/notifications" not in paths:
        @app.get("/api/mlx/automations/notifications")
        def automation_notifications(
            limit: int = Query(default=50, ge=1, le=200),
            unread_only: bool = False,
        ):
            query = urllib.parse.urlencode({
                "limit": str(limit),
                "unread_only": "true" if unread_only else "false",
            })
            return agent_json_request(
                "GET",
                "/api/automations/notifications?" + query,
                timeout=15,
            )

        @app.post("/api/mlx/automations/notifications/read-all")
        def automation_notifications_read_all():
            return agent_json_request(
                "POST",
                "/api/automations/notifications/read-all",
                {},
                timeout=15,
            )

        @app.post("/api/mlx/automations/notifications/{notification_id}/read")
        def automation_notification_read(notification_id: str):
            return agent_json_request(
                "POST",
                "/api/automations/notifications/" +
                urllib.parse.quote(notification_id, safe="") + "/read",
                {},
                timeout=15,
            )

    if "/api/mlx/automations/{automation_id}" not in paths:
        @app.get("/api/mlx/automations/{automation_id}")
        def automation_get(automation_id: str):
            return agent_json_request(
                "GET",
                "/api/automations/" + urllib.parse.quote(automation_id, safe=""),
                timeout=15,
            )

        @app.put("/api/mlx/automations/{automation_id}")
        def automation_update(automation_id: str, request: dict):
            return agent_json_request(
                "PUT",
                "/api/automations/" + urllib.parse.quote(automation_id, safe=""),
                request,
                timeout=15,
            )

        @app.delete("/api/mlx/automations/{automation_id}")
        def automation_delete(automation_id: str):
            return agent_json_request(
                "DELETE",
                "/api/automations/" + urllib.parse.quote(automation_id, safe=""),
                timeout=15,
            )

    if "/api/mlx/automations/{automation_id}/run" not in paths:
        @app.post("/api/mlx/automations/{automation_id}/run", status_code=202)
        def automation_run_now(automation_id: str):
            return agent_json_request(
                "POST",
                "/api/automations/" + urllib.parse.quote(automation_id, safe="") + "/run",
                {},
                timeout=15,
            )

    if "/api/mlx/automations/runs/{run_id}" not in paths:
        @app.get("/api/mlx/automations/runs/{run_id}")
        def automation_run_get(run_id: str):
            return agent_json_request(
                "GET",
                "/api/automations/runs/" + urllib.parse.quote(run_id, safe=""),
                timeout=15,
            )


__all__ = ["install_routes"]
