"""Local-only, opt-in chat history search and privacy controls."""
from __future__ import annotations

from fastapi import HTTPException
from agent import chat_archive


def install_routes(app, chat_host):
    @app.get("/api/chat-archive/status")
    def archive_status():
        return chat_archive.status()

    @app.post("/api/chat-archive/config")
    def archive_config(payload: dict):
        if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
            raise HTTPException(422, "enabled must be boolean")
        enabled = payload["enabled"]
        result = chat_archive.set_enabled(enabled)
        if enabled:
            # Explicit opt-in triggers a local backfill of existing chats;
            # individual future PUTs are indexed incrementally.
            with chat_host.CHATS_LOCK:
                result.update(chat_archive.rebuild(chat_host.list_chats()))
        return result

    @app.post("/api/chat-archive/rebuild")
    def archive_rebuild():
        if not chat_archive.enabled():
            raise HTTPException(409, "Chat archive is disabled")
        with chat_host.CHATS_LOCK:
            return chat_archive.rebuild(chat_host.list_chats())

    @app.get("/api/chat-archive/search")
    def archive_search(query: str, limit: int = 6):
        return {
            "query": query,
            "results": chat_archive.search(query, limit=limit),
        }

    @app.get("/api/chat-archive/activities")
    def archive_activities(kind: str = "", limit: int = 25, offset: int = 0):
        if kind not in ("", "image", "video", "agent", "tool"):
            raise HTTPException(422, "Invalid activity kind")
        from agent import archive_activity_context
        return archive_activity_context.inventory(
            kind=kind, limit=limit, offset=offset,
        )

    @app.post("/api/chat-archive/exclude/{chat_id}")
    def archive_exclude(chat_id: str):
        chat_host.validate_chat_id(chat_id)
        chat_archive.remove_chat(chat_id, exclude=True)
        return {"ok": True, "chat_id": chat_id, "excluded": True}

    @app.post("/api/chat-archive/include/{chat_id}")
    def archive_include(chat_id: str):
        chat_host.validate_chat_id(chat_id)
        with chat_host.CHATS_LOCK:
            chat = chat_host.read_chat(chat_id)
            if chat is None:
                raise HTTPException(404, "Chat not found")
            chat_archive.include_chat(chat_id)
            chat_archive.index_chat(chat)
        return {"ok": True, "chat_id": chat_id, "excluded": False}
