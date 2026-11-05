"""Explicit opt-in controls for locally run Qwen personal-memory extraction."""
from fastapi import HTTPException
from agent import semantic_personal_memory as smart
from agent import dedicated_memory_model


def install_routes(app, chat_host):
    @app.get("/api/smart-memory/status")
    def smart_status():
        return smart.status()

    @app.get("/api/smart-memory/model")
    def memory_model_status():
        try:
            return dedicated_memory_model.status()
        except dedicated_memory_model.MemoryModelError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.get("/api/smart-memory/supervisor")
    def memory_supervisor_status():
        from agent import memory_model_coordination as coordination
        data = coordination.supervisor_state()
        return {
            "state": data.get("state", "not_installed"),
            "managed": bool(data.get("owned", False)),
            "extraction_paused_for_resources": bool(data.get("pause_extraction", False)),
        }

    @app.post("/api/smart-memory/model")
    def memory_model_config(payload: dict):
        try:
            return dedicated_memory_model.configure(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except dedicated_memory_model.MemoryModelError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/smart-memory/config")
    def smart_config(payload: dict):
        if type(payload.get("enabled")) is not bool:
            raise HTTPException(422, "enabled must be boolean")
        try:
            return smart.set_enabled(payload["enabled"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/smart-memory/backfill")
    def smart_backfill(payload: dict | None = None):
        max_messages = (payload or {}).get("limit", 60)
        if type(max_messages) is not int or not 1 <= max_messages <= 100:
            raise HTTPException(422, "limit must be between 1 and 100")
        try:
            if (payload or {}).get("full") is True:
                from agent import smart_full_history
                if hasattr(chat_host, 'iter_memory_chats'):
                    return smart_full_history.start(chat_host.iter_memory_chats)
                with chat_host.CHATS_LOCK: chats = chat_host.list_chats()
                return smart_full_history.start(chats)
            with chat_host.CHATS_LOCK: chats = chat_host.list_chats()
            return smart.backfill(chats, limit=max_messages)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
