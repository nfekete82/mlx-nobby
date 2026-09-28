"""Production agent entrypoint with optional feature route/runtime layers."""

from agent.shorts_consistency_runtime import install_runtime as install_shorts_consistency_runtime

# Install before importing agent.app: app import resumes durable Shorts jobs, and
# recovered consistency-mode projects must already see the keyframe/I2V worker.
install_shorts_consistency_runtime()

from agent.app import app
from agent.shorts_studio_routes import install_routes as install_shorts_studio_routes


install_shorts_studio_routes(app)

__all__ = ["app"]
