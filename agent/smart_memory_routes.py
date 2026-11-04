"""Explicit opt-in controls for locally run Qwen personal-memory extraction."""
from fastapi import HTTPException
from agent import semantic_personal_memory as smart


def install_routes(app, chat_host):
    @app.get("/api/smart-memory/status")
    def smart_status():
        return smart.status()

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
            with chat_host.CHATS_LOCK:
                # Never stream private content to the client. Queue only
                # native-host tasks; inference happens asynchronously.
                chats = chat_host.list_chats()
            if (payload or {}).get("full") is True:
                from agent import smart_full_history
                return smart_full_history.start(chats)
            return smart.backfill(chats, limit=max_messages)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
