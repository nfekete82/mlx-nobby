"""FastAPI routes for the local MLX nobby memory store."""

from fastapi import HTTPException

from agent import memory


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
            item = memory.add(
                payload.get("text"),
                category=payload.get("category"),
                importance=payload.get("importance", 0.7),
                confidence=payload.get("confidence", 0.9),
                source_chat_id=payload.get("source_chat_id"),
                pinned=payload.get("pinned") is True,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"memory": item}

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
            item = memory.update(memory_id, **allowed)
        except KeyError as exc:
            raise HTTPException(404, "Memory nicht gefunden") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"memory": item}

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
        return memory.observe_user_message(
            message,
            source_chat_id=payload.get("source_chat_id"),
        )

    @app.get("/api/memory/context")
    def memory_context(query: str, limit: int = memory.DEFAULT_LIMIT):
        return {
            "query": query,
            "memories": memory.retrieve(query, limit=limit),
            "context": memory.context(query, limit=limit),
        }
