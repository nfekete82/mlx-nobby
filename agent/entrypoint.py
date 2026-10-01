"""Production agent entrypoint with optional feature route/runtime layers."""

from agent.shorts_caption_runtime import install_runtime as install_shorts_caption_runtime
from agent.shorts_consistency_runtime import install_runtime as install_shorts_consistency_runtime

# Install before importing agent.app: app import resumes durable Shorts jobs, so
# recovered jobs must already see both the caption and consistency runtimes.
install_shorts_caption_runtime()
install_shorts_consistency_runtime()

from agent.app import (
    MODEL_RUNTIME_LOCK,
    app,
    find_server_pid,
    load_config,
    load_models,
    status as runtime_status,
    switch_model_runtime,
)
from agent.automation_routes import install_routes as install_automation_routes
from agent.image_generation_intent_runtime import install_runtime as install_image_generation_intent_runtime
from agent.image_pipeline_routes import install_routes as install_image_pipeline_routes
from agent.image_prompt_quality_runtime import install_runtime as install_image_prompt_quality_runtime
from agent.media_queue_performance import install as install_media_queue_performance
from agent.memory_middleware import MemoryChatMiddleware
from agent.memory_routes import install_routes as install_memory_routes
from agent.model_scout_routes import install_routes as install_model_scout_routes
from agent.performance_observatory_routes import install_routes as install_performance_observatory_routes
from agent.runtime_reliability_routes import install_routes as install_runtime_reliability_routes
from agent.shorts_studio_routes import install_routes as install_shorts_studio_routes
from agent.speech_streaming_routes import install_routes as install_speech_streaming_routes
from agent.system_health_performance import install as install_system_health_performance
from agent.system_health_routes import install_routes as install_system_health_routes
from agent.voice_manager_routes import install_routes as install_voice_manager_routes


# Standard browser text chat streams directly through agent.app instead of the
# ModelProvider. Enrich that path at the ASGI boundary while leaving strict
# helper/model calls untouched.
app.add_middleware(MemoryChatMiddleware)

install_image_generation_intent_runtime()
install_image_prompt_quality_runtime()
install_media_queue_performance()
install_image_pipeline_routes(app)
install_memory_routes(app)
install_model_scout_routes(
    app,
    model_provider=load_models,
    config_provider=load_config,
    switch_model=switch_model_runtime,
    runtime_lock=MODEL_RUNTIME_LOCK,
    find_server_pid=find_server_pid,
)
install_shorts_studio_routes(app)
install_speech_streaming_routes(app)
install_voice_manager_routes(app)
install_runtime_reliability_routes(app, status_provider=runtime_status)
install_performance_observatory_routes(app, status_provider=runtime_status)
install_system_health_performance()
install_system_health_routes(app)
install_automation_routes(app)

__all__ = ["app"]
