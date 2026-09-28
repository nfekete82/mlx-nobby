"""Production agent entrypoint with optional feature route layers."""

from agent.app import app
from agent.shorts_studio_routes import install_routes as install_shorts_studio_routes


install_shorts_studio_routes(app)

__all__ = ["app"]
