"""Production agent entrypoint with optional feature route/runtime layers."""

from agent.shorts_caption_runtime import install_runtime as install_shorts_caption_runtime
from agent.shorts_consistency_runtime import install_runtime as install_shorts_consistency_runtime

# Install before importing agent.app: app import resumes durable Shorts jobs, so
# recovered jobs must already see both the caption and consistency runtimes.
install_shorts_caption_runtime()
install_shorts_consistency_runtime()

from agent.app import app
from agent.shorts_studio_routes import install_routes as install_shorts_studio_routes


install_shorts_studio_routes(app)

__all__ = ["app"]
