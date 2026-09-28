"""Production agent entrypoint with optional feature route/runtime layers."""

from agent.shorts_caption_runtime import install_runtime as install_shorts_caption_runtime
from agent.shorts_consistency_runtime import install_runtime as install_shorts_consistency_runtime

# Install before importing agent.app: app import resumes durable Shorts jobs, so
# recovered jobs must already see both the caption and consistency runtimes.
install_shorts_caption_runtime()
install_shorts_consistency_runtime()

from agent.app import app, status as runtime_status
from agent.runtime_reliability_routes import install_routes as install_runtime_reliability_routes
from agent.shorts_studio_routes import install_routes as install_shorts_studio_routes
from agent.speech_streaming_routes import install_routes as install_speech_streaming_routes
from agent.voice_manager_routes import install_routes as install_voice_manager_routes


install_shorts_studio_routes(app)
install_speech_streaming_routes(app)
install_voice_manager_routes(app)
install_runtime_reliability_routes(app, status_provider=runtime_status)

__all__ = ["app"]
