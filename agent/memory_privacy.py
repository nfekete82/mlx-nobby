"""Privacy cleanup helpers for consolidated long-term memory."""

from __future__ import annotations

import sqlite3

from agent import memory_consolidation


def _connect(db_path):
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    memory_consolidation.ensure_schema(connection)
    return connection


def purge_cluster(db_path, seed_ids) -> dict:
    """Delete all memories/audit rows connected to explicitly forgotten IDs.

    Consolidation history can form chains (A -> B -> C). Explicit forget should
    not leave disabled historical variants or text snapshots behind, so the
    relation graph is traversed in both directions before deletion.
    """
    seeds = {str(value) for value in (seed_ids or []) if value}
    if not seeds:
        return {"memory_ids": [], "memories_deleted": 0, "events_deleted": 0}

    try:
        with _connect(db_path) as connection:
            related = set(seeds)
            queue = list(seeds)
            while queue:
                current = queue.pop()
                rows = connection.execute(
                    """
                    SELECT primary_memory_id, absorbed_memory_id
                    FROM memory_consolidations
                    WHERE primary_memory_id = ? OR absorbed_memory_id = ?
                    """,
                    (current, current),
                ).fetchall()
                for row in rows:
                    for value in (row["primary_memory_id"], row["absorbed_memory_id"]):
                        if value and value not in related:
                            related.add(value)
                            queue.append(value)

            ids = sorted(related)
            placeholders = ",".join("?" for _ in ids)
            memory_cursor = connection.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders})",
                ids,
            )
            event_cursor = connection.execute(
                f"""
                DELETE FROM memory_consolidations
                WHERE primary_memory_id IN ({placeholders})
                   OR absorbed_memory_id IN ({placeholders})
                """,
                [*ids, *ids],
            )
            connection.commit()
            return {
                "memory_ids": ids,
                "memories_deleted": int(memory_cursor.rowcount),
                "events_deleted": int(event_cursor.rowcount),
            }
    except sqlite3.Error as exc:
        return {
            "memory_ids": sorted(seeds),
            "memories_deleted": 0,
            "events_deleted": 0,
            "error": str(exc),
        }


def purge_audit_for_memory(db_path, memory_id: str) -> dict:
    """Remove audit snapshots for one manually deleted memory only."""
    memory_id = str(memory_id or "").strip()
    if not memory_id:
        return {"events_deleted": 0}
    try:
        with _connect(db_path) as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_consolidations
                WHERE primary_memory_id = ? OR absorbed_memory_id = ?
                """,
                (memory_id, memory_id),
            )
            connection.commit()
            return {"events_deleted": int(cursor.rowcount)}
    except sqlite3.Error as exc:
        return {"events_deleted": 0, "error": str(exc)}


__all__ = ["purge_audit_for_memory", "purge_cluster"]
