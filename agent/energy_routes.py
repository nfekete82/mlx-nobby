"""Read-only host-side energy history API."""
from fastapi import FastAPI
from agent.energy_monitor import snapshot


def install_routes(app: FastAPI):
    @app.get("/api/system/energy")
    def energy_snapshot():
        return snapshot()


__all__ = ["install_routes"]
