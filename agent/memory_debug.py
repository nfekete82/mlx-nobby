"""Read-only diagnostics for Nobby Memory retrieval.

This module mirrors the production scoring formula from ``agent.memory`` but
never updates ``last_used_at`` or ``use_count``. It is intentionally kept out
of the normal chat path so diagnostics cannot add latency to user requests.
"""

from __future__ import annotations

import time

from agent import memory
from agent import memory_embeddings


HYBRID_WEIGHTS = {
    "semantic": 0.58,
    "lexical": 0.20,
    "importance": 0.10,
    "confidence": 0.05,
    "recency": 0.04,
    "pinned": 0.12,
}
LEXICAL_WEIGHTS = {
    "semantic": 0.0,
    "lexical": 0.60,
    "importance": 0.20,
    "confidence": 0.08,
    "recency": 0.07,
    "pinned": 0.20,
}


def _round(value):
    if value is None:
        return None
    return round(float(value), 6)


def inspect(query, *, limit=memory.DEFAULT_LIMIT) -> dict:
    """Return a side-effect-free explanation of memory retrieval for ``query``.

    The production memory store is read only. Selected entries are not marked
    as used, which keeps this developer tool from influencing future ranking.
    """
    query = str(query or "").strip()
    limit = max(1, min(int(limit), memory.MAX_LIMIT))
    if not query:
        return {
            "query": "",
            "mode": "none",
            "limit": limit,
            "eligible_count": 0,
            "selected": [],
            "context": "",
        }

    memories = memory.list_memories(limit=500)
    now = time.time()
    query_tokens = memory._tokens(query)
    semantic_scores = memory_embeddings.semantic_scores(
        memory.MEMORY_DB,
        memories,
        query,
    )
    semantic_available = semantic_scores is not None
    weights = HYBRID_WEIGHTS if semantic_available else LEXICAL_WEIGHTS
    eligible = []

    for item in memories:
        lexical = memory._lexical_score(query_tokens, memory._tokens(item["text"]))
        age_days = max(0.0, (now - float(item["updated_at"])) / 86400.0)
        recency = 1.0 / (1.0 + age_days / 90.0)
        semantic = (
            max(0.0, float(semantic_scores.get(item["id"], 0.0)))
            if semantic_available
            else None
        )

        if semantic_available:
            if (
                query_tokens
                and lexical == 0.0
                and semantic < memory_embeddings.MIN_SEMANTIC_SIMILARITY
                and not item["pinned"]
            ):
                continue
        elif query_tokens and lexical == 0.0 and not item["pinned"]:
            continue

        contributions = {
            "semantic": (semantic or 0.0) * weights["semantic"],
            "lexical": lexical * weights["lexical"],
            "importance": float(item["importance"]) * weights["importance"],
            "confidence": float(item["confidence"]) * weights["confidence"],
            "recency": recency * weights["recency"],
            "pinned": weights["pinned"] if item["pinned"] else 0.0,
        }
        score = sum(contributions.values())
        eligible.append({
            "memory": item,
            "score": score,
            "semantic": semantic,
            "lexical": lexical,
            "recency": recency,
            "contributions": contributions,
        })

    eligible.sort(
        key=lambda entry: (
            entry["score"],
            float(entry["memory"]["updated_at"]),
        ),
        reverse=True,
    )
    selected = eligible[:limit]

    result_items = []
    for entry in selected:
        item = entry["memory"]
        result_items.append({
            "memory": item,
            "score": _round(entry["score"]),
            "semantic": _round(entry["semantic"]),
            "lexical": _round(entry["lexical"]),
            "importance": _round(item.get("importance")),
            "confidence": _round(item.get("confidence")),
            "recency": _round(entry["recency"]),
            "pinned_bonus": _round(entry["contributions"]["pinned"]),
            "contributions": {
                key: _round(value)
                for key, value in entry["contributions"].items()
            },
        })

    selected_memories = [entry["memory"] for entry in selected]
    return {
        "query": query,
        "mode": "hybrid" if semantic_available else "lexical",
        "limit": limit,
        "eligible_count": len(eligible),
        "selected": result_items,
        "context": memory.context_from_memories(selected_memories),
        "weights": weights,
        "semantic_threshold": (
            memory_embeddings.MIN_SEMANTIC_SIMILARITY
            if semantic_available
            else None
        ),
    }


__all__ = ["inspect"]
