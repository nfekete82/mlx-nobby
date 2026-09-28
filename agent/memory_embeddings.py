"""Semantic embeddings for Nobby Memory.

This module reuses the local embedding service on port 8020. It keeps vectors
inside the same SQLite database as long-term memory and degrades to ``None``
when the embedding runtime is unavailable so callers can fall back to lexical
retrieval without breaking chat.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import struct
import time
import urllib.error
import urllib.request


EMBEDDINGS_URL = os.environ.get(
    "MEMORY_EMBEDDINGS_URL",
    os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:8020"),
).rstrip("/")
EMBEDDINGS_TIMEOUT = float(
    os.environ.get("MLX_MEMORY_EMBEDDING_TIMEOUT", "12")
)
EMBEDDING_BATCH_SIZE = max(
    1,
    min(int(os.environ.get("MLX_MEMORY_EMBEDDING_BATCH_SIZE", "64")), 128),
)
EMBEDDING_BACKFILL_PER_REQUEST = max(
    1,
    min(int(os.environ.get("MLX_MEMORY_EMBEDDING_BACKFILL_PER_REQUEST", "32")), 128),
)
MIN_SEMANTIC_SIMILARITY = max(
    0.0,
    min(float(os.environ.get("MLX_MEMORY_MIN_SEMANTIC_SIMILARITY", "0.35")), 1.0),
)
QUERY_INSTRUCTION = os.environ.get(
    "MLX_MEMORY_EMBEDDING_QUERY_INSTRUCTION",
    (
        "Given a user message, retrieve relevant long-term user memories, "
        "preferences, stable facts, and communication preferences"
    ),
).strip()

_HEALTH_TTL_SECONDS = 5.0
_health_cache = {"expires": 0.0, "value": None}


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector BLOB NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model
            ON memory_embeddings(model, dimensions);
        """
    )


def _request(path: str, payload=None, *, timeout=EMBEDDINGS_TIMEOUT):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        EMBEDDINGS_URL + path,
        data=data,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _model_key(payload: dict) -> str | None:
    value = payload.get("upstream_model") or payload.get("model")
    value = str(value or "").strip()
    return value or None


def embedding_health(*, force=False):
    now = time.monotonic()
    if not force and now < _health_cache["expires"]:
        return _health_cache["value"]
    try:
        health = _request("/health", timeout=min(EMBEDDINGS_TIMEOUT, 5.0))
        if not isinstance(health, dict) or health.get("ok") is not True:
            health = None
        elif not _model_key(health) or not int(health.get("dimensions") or 0):
            health = None
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        health = None
    _health_cache["value"] = health
    _health_cache["expires"] = now + _HEALTH_TTL_SECONDS
    return health


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pack(vector) -> bytes:
    return struct.pack("<%sf" % len(vector), *[float(value) for value in vector])


def _unpack(blob: bytes):
    return struct.unpack("<%sf" % (len(blob) // 4), blob)


def _query_text(query: str) -> str:
    query = str(query or "").strip()
    if not QUERY_INSTRUCTION:
        return query
    return f"Instruct: {QUERY_INSTRUCTION}\nQuery: {query}"


def _validate_response(response, expected_count, *, expected_model=None, expected_dimensions=None):
    if not isinstance(response, dict):
        raise RuntimeError("invalid embedding response")
    vectors = response.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise RuntimeError("invalid embedding vector count")
    dimensions = int(response.get("dimensions") or 0)
    model = _model_key(response)
    if not model or dimensions <= 0:
        raise RuntimeError("embedding model metadata missing")
    if expected_model and model != expected_model:
        raise RuntimeError("embedding model changed during memory indexing")
    if expected_dimensions and dimensions != expected_dimensions:
        raise RuntimeError("embedding dimensions changed during memory indexing")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise RuntimeError("invalid embedding vector")
    return model, dimensions, vectors


def _cosine(left, right) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _connect(db_path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    ensure_schema(connection)
    return connection


def _backfill(connection, memories, *, model, dimensions) -> int:
    missing = []
    for item in memories:
        content_hash = _hash(item["text"])
        row = connection.execute(
            """
            SELECT memory_id FROM memory_embeddings
            WHERE memory_id = ? AND model = ? AND dimensions = ? AND content_hash = ?
            """,
            (item["id"], model, dimensions, content_hash),
        ).fetchone()
        if row is None:
            missing.append((item, content_hash))
            if len(missing) >= EMBEDDING_BACKFILL_PER_REQUEST:
                break

    written = 0
    for offset in range(0, len(missing), EMBEDDING_BATCH_SIZE):
        group = missing[offset:offset + EMBEDDING_BATCH_SIZE]
        response = _request(
            "/embeddings",
            {"texts": [item["text"] for item, _hash_value in group]},
        )
        response_model, response_dimensions, vectors = _validate_response(
            response,
            len(group),
            expected_model=model,
            expected_dimensions=dimensions,
        )
        now = time.time()
        for (item, content_hash), vector in zip(group, vectors):
            connection.execute(
                """
                INSERT OR REPLACE INTO memory_embeddings
                    (memory_id, model, dimensions, vector, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    response_model,
                    response_dimensions,
                    _pack(vector),
                    content_hash,
                    now,
                ),
            )
            written += 1
        connection.commit()
    return written


def semantic_scores(db_path, memories, query):
    """Return ``memory_id -> cosine similarity`` or ``None`` on fallback.

    Existing v1 databases are upgraded lazily. Missing, stale, or differently
    modelled vectors are regenerated in bounded batches when semantic retrieval
    is used. A single chat request therefore cannot trigger an unbounded backfill.
    """
    query = str(query or "").strip()
    if not query or not memories:
        return {}
    health = embedding_health()
    if not health:
        return None
    model = _model_key(health)
    dimensions = int(health.get("dimensions") or 0)
    if not model or dimensions <= 0:
        return None

    try:
        with _connect(db_path) as connection:
            _backfill(
                connection,
                memories,
                model=model,
                dimensions=dimensions,
            )
            query_response = _request(
                "/embedding",
                {"text": _query_text(query)},
            )
            query_model, query_dimensions, vectors = _validate_response(
                query_response,
                1,
                expected_model=model,
                expected_dimensions=dimensions,
            )
            query_vector = vectors[0]
            scores = {}
            for item in memories:
                row = connection.execute(
                    """
                    SELECT vector FROM memory_embeddings
                    WHERE memory_id = ? AND model = ? AND dimensions = ? AND content_hash = ?
                    """,
                    (
                        item["id"],
                        query_model,
                        query_dimensions,
                        _hash(item["text"]),
                    ),
                ).fetchone()
                if row is not None:
                    scores[item["id"]] = _cosine(query_vector, _unpack(row["vector"]))
            return scores
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        sqlite3.Error,
        json.JSONDecodeError,
    ):
        return None


def status(db_path=None):
    health = embedding_health()
    result = {
        "available": bool(health),
        "mode": "hybrid" if health else "lexical_fallback",
        "service_url": EMBEDDINGS_URL,
        "model": _model_key(health or {}),
        "dimensions": int((health or {}).get("dimensions") or 0) or None,
        "min_similarity": MIN_SEMANTIC_SIMILARITY,
        "backfill_per_request": EMBEDDING_BACKFILL_PER_REQUEST,
    }
    if db_path is not None:
        try:
            with _connect(db_path) as connection:
                result["stored_vectors"] = connection.execute(
                    "SELECT count(*) FROM memory_embeddings"
                ).fetchone()[0]
        except sqlite3.Error:
            result["stored_vectors"] = 0
    return result
