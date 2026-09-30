"""Production web entrypoint with feature route layers."""

from backend.app import AGENT_URL, agent_json_request, app, mlx_chat_stream
from backend.automation_routes import install_routes as install_automation_routes
from backend.chat_reliability_routes import install_routes as install_chat_reliability_routes
from backend.media_routing_ui import (
    MediaRoutingUiMiddleware,
    install_routes as install_routing_observatory_routes,
)
from backend.memory_manager_routes import (
    MemoryManagerUiMiddleware,
    install_routes as install_memory_manager_routes,
)
from backend.model_scout_routes import (
    ModelScoutUiMiddleware,
    install_routes as install_model_scout_routes,
)
from backend.negative_prompt_ui import NegativePromptUiMiddleware
from backend.settings_ui_routes import SettingsUiMiddleware
from backend.shorts_studio_routes import install_routes as install_shorts_studio_routes
from backend.speech_streaming_routes import install_routes as install_speech_streaming_routes
from backend.system_health_routes import (
    SystemHealthUiMiddleware,
    install_routes as install_system_health_routes,
)
from backend.version_routes import install_routes as install_version_routes
from backend.voice_manager_routes import install_routes as install_voice_manager_routes


app.add_middleware(MemoryManagerUiMiddleware)
app.add_middleware(SystemHealthUiMiddleware)
app.add_middleware(ModelScoutUiMiddleware)
app.add_middleware(SettingsUiMiddleware)
app.add_middleware(MediaRoutingUiMiddleware)
app.add_middleware(NegativePromptUiMiddleware)

install_automation_routes(app, agent_json_request)
install_memory_manager_routes(app, agent_json_request)
install_model_scout_routes(app, agent_json_request)
install_shorts_studio_routes(app, agent_json_request)
install_speech_streaming_routes(app, AGENT_URL)
install_voice_manager_routes(app, AGENT_URL)
install_version_routes(app)
install_system_health_routes(app, agent_json_request)
install_routing_observatory_routes(app)
install_chat_reliability_routes(
    app,
    stream_factory=mlx_chat_stream,
    agent_url=AGENT_URL,
)

__all__ = ["app"]
