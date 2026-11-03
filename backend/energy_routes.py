"""Browser-to-local-agent energy proxy; no filesystem access inside Docker."""
from fastapi import FastAPI, HTTPException


def install_routes(app: FastAPI, agent_json_request):
    @app.get("/api/mlx/system/energy")
    def energy_proxy():
        try:
            return agent_json_request("GET", "/api/system/energy", timeout=12)
        except HTTPException as exc:
            raise HTTPException(
                status_code=503, detail="Energiedaten derzeit nicht erreichbar"
            ) from exc


__all__ = ["install_routes"]
