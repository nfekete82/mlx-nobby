"""Lifecycle helpers that combine memory writes with conservative consolidation."""

from __future__ import annotations

from agent import memory
from agent import memory_consolidation
from agent import memory_privacy
from agent import memory_dashboard
from agent import personal_memory


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
    if memory_dashboard.paused():
        return {"action": "paused"}
    event = memory.observe_user_message(message, source_chat_id=source_chat_id)

    if event.get("action") == "forgot":
        removed_ids = [
            item.get("id")
            for item in (event.get("memories") or [])
            if isinstance(item, dict) and item.get("id")
        ]
        privacy = memory_privacy.purge_cluster(memory.MEMORY_DB, removed_ids)
        return {**event, "privacy_cleanup": privacy}

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


def delete_memory(memory_id):
    deleted = memory.delete(memory_id)
    if not deleted:
        return {"deleted": False, "privacy_cleanup": {"events_deleted": 0}}
    privacy = memory_privacy.purge_audit_for_memory(memory.MEMORY_DB, memory_id)
    return {"deleted": True, "privacy_cleanup": privacy}


def enrich_messages(messages, *, source_chat_id=None, observe=True, limit=memory.DEFAULT_LIMIT):
    copied = [dict(message) for message in (messages or [])]
    last_turn = next((
        message.get("content") for message in reversed(copied)
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
    ), None)
    if last_turn and memory._EXPLICIT_FORGET.match(last_turn):
        return memory.attach_system_context(
            copied,
            "RETENTION POLICY: This chat request did not delete any memory. "
            "Do not claim to have forgotten or erased data. Explain that "
            "permanent deletion requires explicit action in Settings > Memory.",
        )
    if memory_dashboard.paused():
        return copied
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

    if personal_memory.recall_requested(memory.recall_query(copied)):
        return fast_personal_context(copied)

    if observe:
        observe_user_message(last_user, source_chat_id=source_chat_id)

    # Retrieval happens only after consolidation so an absorbed older memory
    # cannot be injected alongside its newer replacement in the same request.
    enriched = memory.enrich_messages(
        copied,
        source_chat_id=source_chat_id,
        observe=False,
        limit=limit,
    )
    try:
        clarification = personal_memory.question_for(last_user, source_chat_id=source_chat_id)
        personal_context = personal_memory.context(
            memory.recall_query(copied), limit=6,
        )
        from agent import knowledge_memory
        knowledge_context = knowledge_memory.context(memory.recall_query(copied), semantic=True)
        extra = "\n\n".join(part for part in (
            clarification, personal_context, knowledge_context,
        ) if part)
        if extra:
            enriched = memory.attach_system_context(enriched, extra[:9000])
    except Exception as error:
        from agent import knowledge_memory
        knowledge_memory.diagnose('recall', error)
    return enriched


def fast_personal_context(messages):
    """Source-aware, bounded-latency fallback for explicit and normal recall.

    Each existing store is read independently: a failed structured/legacy
    lookup must never erase already available, user-confirmed personal facts.
    No embeddings, extraction or model inference runs in this fallback.
    """
    copied = [dict(message) for message in (messages or [])]
    if memory_dashboard.paused():
        return copied
    query = memory.recall_query(copied)
    if not query:
        return copied

    from agent import knowledge_memory, chat_archive
    explicit = personal_memory.recall_requested(query)
    parts = []
    failed = False

    def include(reader):
        nonlocal failed
        try:
            value = reader()
        except Exception as error:
            failed = True
            try:
                knowledge_memory.diagnose('recall', error)
            except Exception:
                pass  # Diagnostics must not erase results from other stores.
            return
        if value:
            parts.append(value)

    # The personal fact inventory is an independent store. Explicit requests
    # previously skipped it entirely and could yield generic/no-evidence text
    # even when a relevant current fact had been saved in SQLite.
    include(lambda: personal_memory.context(query, limit=12 if explicit else 6))
    include(lambda: knowledge_memory.context(
        query, budget=18000 if explicit else 3000,
    ))

    if explicit:
        include(lambda: chat_archive.context(query, limit=8))
        include(lambda: memory.explicit_context(query))
    elif memory.MEMORY_DB.exists():
        # Keep only relevant lexical legacy matches and global communication
        # preferences. Never dump unrelated pinned notes into ordinary chat.
        include(lambda: memory.explicit_context(
            query, include_global_preferences=True,
        ))

    if parts:
        # One index may correctly have no match even if another contains the
        # requested fact. Avoid contradictory no-evidence guidance next to a
        # source-backed answer from the personal facts, archive or legacy DB.
        if any(not part.startswith(
            'LOCAL STRUCTURED KNOWLEDGE: No matching stored evidence for this question.'
        ) for part in parts):
            parts = [part for part in parts if not part.startswith(
                'LOCAL STRUCTURED KNOWLEDGE: No matching stored evidence for this question.'
            )]
        if explicit:
            # Response guidance applies to evidence from every source; it is
            # separate from untrusted archived user messages and quotes.
            parts.insert(0,
                'EXPLICIT LOCAL RECALL REQUEST. Answer the user\'s specific '
                'question with the matching stored facts and their sources '
                'rather than generic examples or a memory-feature overview. '
                'The stores are independent; a no-match in one does not '
                'negate evidence in another. Do not invent missing dates, '
                'names or completion claims. Current user corrections '
                'override older or unresolved records.')
        return memory.attach_system_context(copied, "\n\n".join(parts))

    if explicit and failed:
        return memory.attach_system_context(copied,
            'LOCAL MEMORY RETRIEVAL UNAVAILABLE. Explain the temporary '
            'retrieval failure. Do not claim there are no stored memories '
            'or invent personal facts.')
    return copied


__all__ = [
    "create_memory",
    "delete_memory",
    "enrich_messages",
    "fast_personal_context",
    "observe_user_message",
    "update_memory",
]
