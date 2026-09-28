"""Production web entrypoint with feature route layers."""

from backend.app import AGENT_URL, agent_json_request, app
from backend.shorts_studio_routes import install_routes as install_shorts_studio_routes
from backend.speech_streaming_routes import install_routes as install_speech_streaming_routes


install_shorts_studio_routes(app, agent_json_request)
install_speech_streaming_routes(app, AGENT_URL)

__all__ = ["app"]
