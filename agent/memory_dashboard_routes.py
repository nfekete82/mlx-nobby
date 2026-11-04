"""Native Agent API: pause/resume recall without deletion and browse all stores."""
from fastapi import HTTPException
from agent import memory_dashboard


def install_routes(app):
    @app.get("/api/memory-dashboard/status")
    def dashboard_status():
        return memory_dashboard.status()

    @app.post("/api/memory-dashboard/pause")
    def dashboard_pause(payload: dict):
        if not isinstance(payload, dict) or type(payload.get("paused")) is not bool:
            raise HTTPException(422, "paused must be boolean")
        return memory_dashboard.set_paused(payload["paused"])

    @app.get("/api/memory-dashboard/items")
    def dashboard_items(source: str, query: str = "", offset: int = 0, limit: int = 20):
        try:
            return memory_dashboard.list_items(source, query=query, offset=offset, limit=limit)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
