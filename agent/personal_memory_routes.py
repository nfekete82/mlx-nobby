"""Local control API for structured personal memory and conflicting facts."""
from fastapi import HTTPException
from agent import personal_memory as pm

def install_routes(app, chat_host):
    @app.get("/api/personal-memory/status")
    def personal_status():
        return pm.status()

    @app.post("/api/personal-memory/config")
    def personal_config(payload: dict):
        if type(payload.get("enabled")) is not bool:
            raise HTTPException(422, "enabled must be boolean")
        result = pm.set_enabled(payload["enabled"])
        if payload["enabled"]:
            with chat_host.CHATS_LOCK:
                result = pm.rebuild(chat_host.list_chats())
        return result

    @app.post("/api/personal-memory/rebuild")
    def personal_rebuild():
        if not pm.enabled():
            raise HTTPException(409, "Personal memory is disabled")
        with chat_host.CHATS_LOCK:
            return pm.rebuild(chat_host.list_chats())

    @app.get("/api/personal-memory/facts")
    def personal_facts(query: str = "", history: bool = False, limit: int = 200):
        return {"facts": pm.list_facts(query, history=history, limit=limit)}

    @app.post("/api/personal-memory/facts")
    def personal_add(payload: dict):
        try:
            return pm.create_fact(
                payload.get("subject"), payload.get("field"),
                payload.get("value"), sensitive=payload.get("sensitive") is True,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/api/personal-memory/facts/{fact_id}")
    def personal_edit(fact_id: str, payload: dict):
        try:
            return pm.edit_fact(
                fact_id,
                subject=payload.get("subject"),
                field=payload.get("field"),
                value=payload.get("value"),
                sensitive=payload.get("sensitive"),
            )
        except KeyError as exc:
            raise HTTPException(404, "Memory not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/personal-memory/facts/{fact_id}")
    def personal_delete(fact_id: str):
        if not pm.delete_fact(fact_id):
            raise HTTPException(404, "Memory not found")
        return {"ok": True}

    @app.get("/api/personal-memory/conflicts")
    def personal_conflicts():
        return {"conflicts": pm.list_conflicts()}

    @app.post("/api/personal-memory/conflicts/{conflict_id}/resolve")
    def personal_resolve(conflict_id: str, payload: dict):
        try:
            return pm.resolve(
                conflict_id, payload.get("decision"),
                custom_value=payload.get("value"),
            )
        except KeyError as exc:
            raise HTTPException(404, "Conflict not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
