"""Conservative consolidation for Nobby Memory.

The planner identifies older memories that represent the same preference slot or
very likely semantic duplicates. It never deletes data: absorbed memories are
disabled and every consolidation is written to an audit table.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import uuid

from agent import memory_embeddings


SEMANTIC_DUPLICATE_THRESHOLD = max(
    0.0,
    min(float(os.environ.get("MLX_MEMORY_CONSOLIDATION_SIMILARITY", "0.965")), 1.0),
)
SEMANTIC_WITH_LEXICAL_THRESHOLD = max(
    0.0,
    min(float(os.environ.get("MLX_MEMORY_CONSOLIDATION_SOFT_SIMILARITY", "0.92")), 1.0),
)
LEXICAL_SUPPORT_THRESHOLD = max(
    0.0,
    min(float(os.environ.get("MLX_MEMORY_CONSOLIDATION_LEXICAL_SUPPORT", "0.60")), 1.0),
)
LEXICAL_FALLBACK_THRESHOLD = max(
    0.0,
    min(float(os.environ.get("MLX_MEMORY_CONSOLIDATION_LEXICAL_FALLBACK", "0.82")), 1.0),
)

_TOKEN_RE = re.compile(r"[\wäöüÄÖÜß-]{2,}", re.UNICODE)
_STOPWORDS = {
    "aber", "also", "auch", "dass", "eine", "einem", "einen", "einer", "eines",
    "für", "fuer", "haben", "ich", "ist", "mit", "nicht", "oder", "sein", "sind",
    "und", "von", "was", "wenn", "wie", "wird", "the", "and", "that", "this",
    "with", "from", "have", "has", "for", "you", "your", "use", "using", "i",
}

_SLOT_PATTERNS = (
    (
        "use",
        re.compile(r"\bf(?:ü|ue)r\s+(.{2,80}?)\s+(?:nutze|verwende)\s+ich\b", re.IGNORECASE),
        1,
    ),
    (
        "use",
        re.compile(r"\bfor\s+(.{2,80}?)\s+i\s+(?:use|prefer)\b", re.IGNORECASE),
        1,
    ),
    (
        "prefer",
        re.compile(
            r"\bich\s+(?:bevorzuge|präferiere|praeferiere)\s+.+?\s+(?:f(?:ü|ue)r|bei)\s+(.{2,80}?)(?:[.!?]|$)",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        "prefer",
        re.compile(r"\bi\s+prefer\s+.+?\s+for\s+(.{2,80}?)(?:[.!?]|$)", re.IGNORECASE),
        1,
    ),
    (
        "model",
        re.compile(
            r"\bmein\s+(?:standardmodell|bevorzugtes\s+modell)\s+f(?:ü|ue)r\s+(.{2,80}?)\s+ist\b",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        "model",
        re.compile(r"\bmy\s+(?:default|preferred)\s+model\s+for\s+(.{2,80}?)\s+is\b", re.IGNORECASE),
        1,
    ),
)

_ADDRESS_PATTERNS = (
    re.compile(r"\b(?:nenn|nenne)\s+mich\s+[\w-]{2,80}\b", re.IGNORECASE),
    re.compile(r"\bcall\s+me\s+[\w-]{2,80}\b", re.IGNORECASE),
    re.compile(r"\bmy\s+preferred\s+name\s+is\s+[\w-]{2,80}\b", re.IGNORECASE),
)


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_consolidations (
            event_id TEXT PRIMARY KEY,
            primary_memory_id TEXT,
            absorbed_memory_id TEXT,
            primary_text TEXT NOT NULL,
            absorbed_text TEXT NOT NULL,
            reason TEXT NOT NULL,
            similarity REAL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_consolidations_primary
            ON memory_consolidations(primary_memory_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_consolidations_absorbed
            ON memory_consolidations(absorbed_memory_id, created_at DESC);
        """
    )


def _normalize_scope(value: str) -> str:
    value = str(value or "").casefold().strip()
    value = re.sub(r"[^\wäöüß-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()[:120]


def slot_key(text: str) -> str | None:
    """Return a conservative replaceable preference slot or ``None``."""
    text = str(text or "").strip()
    if not text:
        return None

    for pattern in _ADDRESS_PATTERNS:
        if pattern.search(text):
            return "address:name"

    for kind, pattern, group in _SLOT_PATTERNS:
        match = pattern.search(text)
        if match:
            scope = _normalize_scope(match.group(group))
            if scope:
                return f"{kind}:{scope}"
    return None


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(str(value or ""))
        if token.casefold() not in _STOPWORDS
    }


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _primary_key(item: dict) -> tuple:
    # The newest durable user statement wins. Pinned/importance/confidence are
    # preserved later during metadata aggregation, so an updated preference can
    # inherit the strength of an older explicit memory without keeping old text.
    return (
        float(item.get("updated_at") or 0.0),
        int(bool(item.get("pinned"))),
        float(item.get("importance") or 0.0),
        float(item.get("confidence") or 0.0),
        float(item.get("created_at") or 0.0),
    )


def plan(db_path, target: dict, candidates: list[dict]) -> dict:
    """Return a consolidation plan without mutating memory rows."""
    if not target or not target.get("enabled", True):
        return {
            "changed": False,
            "primary_id": target.get("id") if target else None,
            "absorbed": [],
        }

    peers = [
        item
        for item in candidates
        if item.get("id") != target.get("id") and item.get("enabled", True)
    ]
    if not peers:
        return {"changed": False, "primary_id": target["id"], "absorbed": []}

    target_slot = slot_key(target.get("text", ""))
    matched: dict[str, dict] = {}

    for item in peers:
        peer_slot = slot_key(item.get("text", ""))
        if target_slot and peer_slot == target_slot:
            matched[item["id"]] = {
                "item": item,
                "reason": "slot_replacement",
                "similarity": lexical_similarity(target["text"], item["text"]),
            }

    semantic_candidates = [
        item
        for item in peers
        if item["id"] not in matched
        and str(item.get("category") or "") == str(target.get("category") or "")
    ]

    semantic_scores = None
    if semantic_candidates:
        semantic_scores = memory_embeddings.semantic_scores(
            db_path,
            semantic_candidates,
            target.get("text", ""),
        )

    for item in semantic_candidates:
        lexical = lexical_similarity(target["text"], item["text"])
        semantic = (
            None
            if semantic_scores is None
            else float(semantic_scores.get(item["id"], 0.0))
        )

        if semantic is None:
            duplicate = lexical >= LEXICAL_FALLBACK_THRESHOLD
        else:
            duplicate = (
                semantic >= SEMANTIC_DUPLICATE_THRESHOLD
                or (
                    semantic >= SEMANTIC_WITH_LEXICAL_THRESHOLD
                    and lexical >= LEXICAL_SUPPORT_THRESHOLD
                )
            )

        if duplicate:
            matched[item["id"]] = {
                "item": item,
                "reason": "semantic_duplicate" if semantic is not None else "lexical_duplicate",
                "similarity": semantic if semantic is not None else lexical,
            }

    if not matched:
        return {"changed": False, "primary_id": target["id"], "absorbed": []}

    cluster = [target] + [entry["item"] for entry in matched.values()]
    primary = max(cluster, key=_primary_key)
    absorbed = []

    for item in cluster:
        if item["id"] == primary["id"]:
            continue
        if item["id"] == target["id"]:
            best = max(
                matched.values(),
                key=lambda entry: float(entry.get("similarity") or 0.0),
            )
            reason = best["reason"]
            similarity = best.get("similarity")
        else:
            entry = matched[item["id"]]
            reason = entry["reason"]
            similarity = entry.get("similarity")
        absorbed.append(
            {
                "id": item["id"],
                "reason": reason,
                "similarity": similarity,
            }
        )

    return {
        "changed": bool(absorbed),
        "primary_id": primary["id"],
        "absorbed": absorbed,
        "slot": target_slot,
    }


def _connect(db_path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    ensure_schema(connection)
    return connection


def _memory_dict(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["pinned"] = bool(item.get("pinned"))
    item["enabled"] = bool(item.get("enabled"))
    return item


def record_event(
    connection: sqlite3.Connection,
    *,
    primary: dict,
    absorbed: dict,
    reason: str,
    similarity: float | None,
) -> str:
    ensure_schema(connection)
    event_id = uuid.uuid4().hex[:24]
    connection.execute(
        """
        INSERT INTO memory_consolidations (
            event_id, primary_memory_id, absorbed_memory_id,
            primary_text, absorbed_text, reason, similarity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            primary.get("id"),
            absorbed.get("id"),
            str(primary.get("text") or ""),
            str(absorbed.get("text") or ""),
            str(reason or "consolidated"),
            None if similarity is None else float(similarity),
            time.time(),
        ),
    )
    return event_id


def consolidate_memory(db_path, memory_id: str) -> dict:
    """Consolidate one enabled memory against the current enabled store."""
    try:
        with _connect(db_path) as connection:
            target = _memory_dict(
                connection.execute(
                    "SELECT * FROM memories WHERE id = ?",
                    (str(memory_id),),
                ).fetchone()
            )
            if target is None:
                return {
                    "changed": False,
                    "primary_id": None,
                    "absorbed": [],
                    "error": "memory_not_found",
                }
            if not target["enabled"]:
                return {
                    "changed": False,
                    "primary_id": target["id"],
                    "absorbed": [],
                    "reason": "memory_disabled",
                }
            candidates = [
                _memory_dict(row)
                for row in connection.execute(
                    "SELECT * FROM memories WHERE enabled = 1 ORDER BY updated_at DESC LIMIT 500"
                ).fetchall()
            ]

        result = plan(db_path, target, candidates)
        if not result.get("changed"):
            return result

        absorbed_ids = [entry["id"] for entry in result["absorbed"]]
        cluster_ids = [result["primary_id"], *absorbed_ids]
        placeholders = ",".join("?" for _ in cluster_ids)

        with _connect(db_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})",
                cluster_ids,
            ).fetchall()
            items = {row["id"]: _memory_dict(row) for row in rows}
            primary = items.get(result["primary_id"])
            if primary is None:
                return {
                    "changed": False,
                    "primary_id": None,
                    "absorbed": [],
                    "error": "primary_missing",
                }

            absorbed_items = [
                items[entry["id"]]
                for entry in result["absorbed"]
                if entry["id"] in items and items[entry["id"]]["enabled"]
            ]
            if not absorbed_items:
                return {
                    "changed": False,
                    "primary_id": primary["id"],
                    "absorbed": [],
                }

            cluster = [primary, *absorbed_items]
            importance = max(float(item.get("importance") or 0.0) for item in cluster)
            confidence = max(float(item.get("confidence") or 0.0) for item in cluster)
            pinned = any(bool(item.get("pinned")) for item in cluster)
            use_count = sum(int(item.get("use_count") or 0) for item in cluster)
            last_used_values = [
                float(item["last_used_at"])
                for item in cluster
                if item.get("last_used_at") is not None
            ]
            last_used_at = max(last_used_values) if last_used_values else None

            connection.execute(
                """
                UPDATE memories
                   SET importance = ?, confidence = ?, pinned = ?,
                       use_count = ?, last_used_at = ?, enabled = 1
                 WHERE id = ?
                """,
                (
                    importance,
                    confidence,
                    int(pinned),
                    use_count,
                    last_used_at,
                    primary["id"],
                ),
            )

            event_ids = []
            applied = []
            by_id = {entry["id"]: entry for entry in result["absorbed"]}
            for absorbed in absorbed_items:
                connection.execute(
                    "UPDATE memories SET enabled = 0 WHERE id = ?",
                    (absorbed["id"],),
                )
                detail = by_id[absorbed["id"]]
                event_ids.append(
                    record_event(
                        connection,
                        primary=primary,
                        absorbed=absorbed,
                        reason=detail["reason"],
                        similarity=detail.get("similarity"),
                    )
                )
                applied.append(detail)
            connection.commit()

        return {
            **result,
            "changed": bool(applied),
            "absorbed": applied,
            "event_ids": event_ids,
            "primary": primary,
        }
    except sqlite3.Error as exc:
        return {
            "changed": False,
            "primary_id": str(memory_id),
            "absorbed": [],
            "error": str(exc),
        }


def consolidate_all(db_path, *, limit=500) -> dict:
    """Conservatively compact the enabled store, newest memories first."""
    limit = max(1, min(int(limit), 1000))
    try:
        with _connect(db_path) as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM memories WHERE enabled = 1 ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
    except sqlite3.Error as exc:
        return {"changed": False, "processed": 0, "absorbed": 0, "error": str(exc)}

    processed = 0
    absorbed = 0
    events = []
    for memory_id in ids:
        result = consolidate_memory(db_path, memory_id)
        processed += 1
        absorbed += len(result.get("absorbed") or []) if result.get("changed") else 0
        events.extend(result.get("event_ids") or [])

    return {
        "changed": absorbed > 0,
        "processed": processed,
        "absorbed": absorbed,
        "event_ids": events,
    }


def list_events(db_path, *, limit=100) -> list[dict]:
    limit = max(1, min(int(limit), 1000))
    try:
        with _connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT event_id, primary_memory_id, absorbed_memory_id,
                       primary_text, absorbed_text, reason, similarity, created_at
                FROM memory_consolidations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def status(db_path) -> dict:
    try:
        with _connect(db_path) as connection:
            events = connection.execute("SELECT count(*) FROM memory_consolidations").fetchone()[0]
            disabled = connection.execute("SELECT count(*) FROM memories WHERE enabled = 0").fetchone()[0]
        return {
            "enabled": True,
            "events": int(events),
            "disabled_memories": int(disabled),
            "semantic_duplicate_threshold": SEMANTIC_DUPLICATE_THRESHOLD,
            "semantic_soft_threshold": SEMANTIC_WITH_LEXICAL_THRESHOLD,
            "lexical_support_threshold": LEXICAL_SUPPORT_THRESHOLD,
            "lexical_fallback_threshold": LEXICAL_FALLBACK_THRESHOLD,
        }
    except sqlite3.Error as exc:
        return {"enabled": False, "error": str(exc)}
