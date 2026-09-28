"""FastAPI routes for the local MLX nobby memory store."""

from fastapi import HTTPException

from agent import memory
from agent import memory_consolidation
from agent import memory_lifecycle


def install_routes(app):
    @app.get("/api/memory")
    def memory_list(include_disabled: bool = False, limit: int = 200):
        return {
            "memories": memory.list_memories(
                include_disabled=include_disabled,
                limit=limit,
            )
        }

    @app.post("/api/memory")
    def memory_create(payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(422, "Ungültiger Memory-Payload")
        try:
            return memory_lifecycle.create_memory(
                payload.get("text"),
                category=payload.get("category"),
                importance=payload.get("importance", 0.7),
                confidence=payload.get("confidence", 0.9),
                source_chat_id=payload.get("source_chat_id"),
                pinned=payload.get("pinned") is True,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/memory/embedding-status")
    def memory_embedding_status():
        return memory.embedding_status()

    @app.get("/api/memory/consolidation-status")
    def memory_consolidation_status():
        return memory_consolidation.status(memory.MEMORY_DB)

    @app.get("/api/memory/consolidations")
    def memory_consolidations(limit: int = 100):
        return {
            "consolidations": memory_consolidation.list_events(
                memory.MEMORY_DB,
                limit=limit,
            )
        }

    @app.post("/api/memory/consolidate")
    def memory_consolidate(payload: dict | None = None):
        payload = payload or {}
        if not isinstance(payload, dict):
            raise HTTPException(422, "Ungültiger Memory-Payload")
        memory_id = payload.get("memory_id")
        if memory_id:
            return memory_consolidation.consolidate_memory(
                memory.MEMORY_DB,
                str(memory_id),
            )
        return memory_consolidation.consolidate_all(
            memory.MEMORY_DB,
            limit=payload.get("limit", 500),
        )

    @app.patch("/api/memory/{memory_id}")
    def memory_update(memory_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(422, "Ungültiger Memory-Payload")
        allowed = {
            key: payload[key]
            for key in (
                "text", "category", "importance", "confidence", "pinned", "enabled"
            )
            if key in payload
        }
        try:
            return memory_lifecycle.update_memory(memory_id, **allowed)
        except KeyError as exc:
            raise HTTPException(404, "Memory nicht gefunden") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/memory/{memory_id}")
    def memory_delete(memory_id: str):
        if not memory.delete(memory_id):
            raise HTTPException(404, "Memory nicht gefunden")
        return {"ok": True}

    @app.post("/api/memory/observe")
    def memory_observe(payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(422, "Ungültiger Memory-Payload")
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(422, "message fehlt")
        return memory_lifecycle.observe_user_message(
            message,
            source_chat_id=payload.get("source_chat_id"),
        )

    @app.get("/api/memory/context")
    def memory_context(query: str, limit: int = memory.DEFAULT_LIMIT):
        selected = memory.retrieve(query, limit=limit)
        return {
            "query": query,
            "memories": selected,
            "context": memory.context_from_memories(selected),
        }
