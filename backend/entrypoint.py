"""Production web entrypoint with feature route layers."""

from backend.app import agent_json_request, app
from backend.shorts_studio_routes import install_routes as install_shorts_studio_routes


install_shorts_studio_routes(app, agent_json_request)

__all__ = ["app"]
