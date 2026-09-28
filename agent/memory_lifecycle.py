"""Lifecycle helpers that combine memory writes with conservative consolidation."""

from __future__ import annotations

from agent import memory
from agent import memory_consolidation


def _consolidate(memory_id: str | None) -> dict:
    if not memory_id:
        return {"changed": False, "primary_id": None, "absorbed": []}
    try:
        return memory_consolidation.consolidate_memory(memory.MEMORY_DB, memory_id)
    except Exception as exc:
        # Consolidation is an optional maintenance layer. Remembering and chat
        # must keep working if it ever fails.
        return {
            "changed": False,
            "primary_id": memory_id,
            "absorbed": [],
            "error": str(exc),
        }


def observe_user_message(message, *, source_chat_id=None):
    event = memory.observe_user_message(message, source_chat_id=source_chat_id)
    if event.get("action") != "remembered":
        return event

    remembered = event.get("memory") or {}
    result = _consolidate(remembered.get("id"))
    primary_id = result.get("primary_id") or remembered.get("id")
    primary = memory.get(primary_id) if primary_id else None

    return {
        **event,
        "memory": primary or remembered,
        "remembered_memory_id": remembered.get("id"),
        "consolidation": result,
    }


def create_memory(
    text,
    *,
    category=None,
    importance=0.7,
    confidence=0.9,
    source_chat_id=None,
    pinned=False,
):
    item = memory.add(
        text,
        category=category,
        importance=importance,
        confidence=confidence,
        source_chat_id=source_chat_id,
        pinned=pinned,
    )
    result = _consolidate(item["id"])
    primary_id = result.get("primary_id") or item["id"]
    return {
        "memory": memory.get(primary_id) or item,
        "created_memory_id": item["id"],
        "consolidation": result,
    }


def update_memory(memory_id, **changes):
    item = memory.update(memory_id, **changes)
    if not item.get("enabled", True):
        return {
            "memory": item,
            "updated_memory_id": item["id"],
            "consolidation": {
                "changed": False,
                "primary_id": item["id"],
                "absorbed": [],
                "reason": "memory_disabled",
            },
        }

    result = _consolidate(item["id"])
    primary_id = result.get("primary_id") or item["id"]
    return {
        "memory": memory.get(primary_id) or item,
        "updated_memory_id": item["id"],
        "consolidation": result,
    }


def enrich_messages(messages, *, source_chat_id=None, observe=True, limit=memory.DEFAULT_LIMIT):
    copied = [dict(message) for message in (messages or [])]
    last_user = next(
        (
            message.get("content")
            for message in reversed(copied)
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ),
        None,
    )
    if not last_user:
        return copied

    if observe:
        observe_user_message(last_user, source_chat_id=source_chat_id)

    # Retrieval happens only after consolidation so an absorbed older memory
    # cannot be injected alongside its newer replacement in the same request.
    return memory.enrich_messages(
        copied,
        source_chat_id=source_chat_id,
        observe=False,
        limit=limit,
    )


__all__ = [
    "create_memory",
    "enrich_messages",
    "observe_user_message",
    "update_memory",
]
