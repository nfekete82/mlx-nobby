"""Persistent automation notifications with optional macOS delivery."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from agent import automations


VALID_LEVELS = {"info", "success", "warning", "error"}


def _now() -> float:
    return time.time()


def _connect():
    automations.ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(automations.AUTOMATIONS_DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    automations._ensure_schema(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS automation_notifications (
            id TEXT PRIMARY KEY,
            automation_id TEXT NOT NULL,
            run_id TEXT NOT NULL UNIQUE,
            level TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at REAL NOT NULL,
            read_at REAL,
            delivered_at REAL,
            delivery_error TEXT,
            FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE,
            FOREIGN KEY (run_id) REFERENCES automation_runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_automation_notifications_created
            ON automation_notifications(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_automation_notifications_unread
            ON automation_notifications(read_at, created_at DESC);
        """
    )
    return connection


def _row_to_notification(row) -> dict:
    item = dict(row)
    item["unread"] = item.get("read_at") is None
    item["delivered"] = item.get("delivered_at") is not None
    return item


def create_notification(
    *,
    automation_id: str,
    run_id: str,
    level: str,
    title: str,
    message: str,
) -> dict:
    level = str(level or "info").strip().lower()
    if level not in VALID_LEVELS:
        raise ValueError("unsupported notification level")
    title = " ".join(str(title or "").strip().split())[:160]
    message = " ".join(str(message or "").strip().split())[:1200]
    if not title or not message:
        raise ValueError("notification title and message are required")

    notification_id = uuid.uuid4().hex[:24]
    now = _now()
    with automations.LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO automation_notifications (
                id, automation_id, run_id, level, title, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_id,
                str(automation_id),
                str(run_id),
                level,
                title,
                message,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM automation_notifications WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
    if row is None:
        raise RuntimeError("notification could not be persisted")
    return _row_to_notification(row)


def list_notifications(*, limit: int = 50, unread_only: bool = False) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with automations.LOCK, _connect() as connection:
        if unread_only:
            rows = connection.execute(
                """
                SELECT * FROM automation_notifications
                 WHERE read_at IS NULL
                 ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM automation_notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_notification(row) for row in rows]


def unread_count() -> int:
    with automations.LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM automation_notifications WHERE read_at IS NULL"
        ).fetchone()
    return int(row["count"] if row else 0)


def mark_read(notification_id: str) -> dict | None:
    now = _now()
    with automations.LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE automation_notifications
               SET read_at = COALESCE(read_at, ?)
             WHERE id = ?
            """,
            (now, str(notification_id)),
        )
        row = connection.execute(
            "SELECT * FROM automation_notifications WHERE id = ?",
            (str(notification_id),),
        ).fetchone()
    return _row_to_notification(row) if row else None


def mark_all_read() -> int:
    now = _now()
    with automations.LOCK, _connect() as connection:
        cursor = connection.execute(
            "UPDATE automation_notifications SET read_at = ? WHERE read_at IS NULL",
            (now,),
        )
        return int(cursor.rowcount or 0)


def mark_delivery(notification_id: str, *, delivered: bool, error: str | None = None) -> dict | None:
    delivered_at = _now() if delivered else None
    with automations.LOCK, _connect() as connection:
        connection.execute(
            """
            UPDATE automation_notifications
               SET delivered_at = ?, delivery_error = ?
             WHERE id = ?
            """,
            (
                delivered_at,
                None if delivered else str(error or "delivery failed")[:1000],
                str(notification_id),
            ),
        )
        row = connection.execute(
            "SELECT * FROM automation_notifications WHERE id = ?",
            (str(notification_id),),
        ).fetchone()
    return _row_to_notification(row) if row else None


def deliver_macos(title: str, message: str) -> tuple[bool, str | None]:
    """Deliver through macOS Notification Center without interpolating AppleScript."""
    if sys.platform != "darwin":
        return False, "native notifications require macOS"

    osascript = shutil.which("osascript") or "/usr/bin/osascript"
    try:
        result = subprocess.run(
            [
                osascript,
                "-e", "on run argv",
                "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e", "end run",
                str(title)[:160],
                str(message)[:600],
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, None
    detail = (result.stderr or result.stdout or "osascript failed").strip()
    return False, detail[:1000]


__all__ = [
    "create_notification",
    "deliver_macos",
    "list_notifications",
    "mark_all_read",
    "mark_delivery",
    "mark_read",
    "unread_count",
]
