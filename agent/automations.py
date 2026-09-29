"""Persistent local automations and schedule calculation for MLX nobby."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path.home() / ".config/mlx-web"
AUTOMATIONS_DB = ROOT / "automations.db"
LOCK = threading.RLock()
VALID_KINDS = {"agent", "model_scout"}
VALID_MODES = {"diagnostic", "research", "coding"}
VALID_SCHEDULE_TYPES = {"manual", "hourly", "daily", "weekly"}
ACTIVE_RUN_STATUSES = {"queued", "running"}


def _now() -> float:
    return time.time()


def _connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AUTOMATIONS_DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS automations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            prompt TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'diagnostic',
            workspace_id TEXT,
            schedule_type TEXT NOT NULL DEFAULT 'manual',
            schedule_time TEXT,
            schedule_weekday INTEGER,
            schedule_minute INTEGER,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            enabled INTEGER NOT NULL DEFAULT 1,
            next_run_at REAL,
            last_run_at REAL,
            last_status TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_automations_due
            ON automations(enabled, next_run_at);

        CREATE TABLE IF NOT EXISTS automation_runs (
            id TEXT PRIMARY KEY,
            automation_id TEXT NOT NULL,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at REAL,
            finished_at REAL,
            result_json TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_automation_runs_task
            ON automation_runs(automation_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_automation_runs_status
            ON automation_runs(status, created_at DESC);
        """
    )


def _clean_text(value, *, max_length, allow_empty=False):
    text = " ".join(str(value or "").strip().split())
    if not text and not allow_empty:
        raise ValueError("value is required")
    return text[:max_length]


def _clean_prompt(value):
    text = str(value or "").strip()
    return text[:12000]


def _zone(name: str) -> ZoneInfo:
    value = str(name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid timezone") from exc


def _parse_clock(value: str | None) -> tuple[int, int]:
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("schedule_time must use HH:MM")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError("schedule_time must use HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("schedule_time must use HH:MM")
    return hour, minute


def normalize_payload(payload: dict, current: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("automation payload must be an object")
    base = dict(current or {})

    name = _clean_text(payload.get("name", base.get("name")), max_length=120)
    kind = str(payload.get("kind", base.get("kind", "agent"))).strip().lower()
    if kind not in VALID_KINDS:
        raise ValueError("unsupported automation kind")

    prompt = _clean_prompt(payload.get("prompt", base.get("prompt", "")))
    if kind == "agent" and not prompt:
        raise ValueError("agent automations require a prompt")

    mode = str(payload.get("mode", base.get("mode", "diagnostic"))).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError("unsupported automation mode")

    workspace_id = payload.get("workspace_id", base.get("workspace_id"))
    if workspace_id is not None:
        workspace_id = _clean_text(workspace_id, max_length=160, allow_empty=True) or None

    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    schedule_type = str(
        schedule.get("type", payload.get("schedule_type", base.get("schedule_type", "manual")))
    ).strip().lower()
    if schedule_type not in VALID_SCHEDULE_TYPES:
        raise ValueError("unsupported schedule type")

    timezone_name = str(
        schedule.get("timezone", payload.get("timezone", base.get("timezone", "UTC")))
    ).strip() or "UTC"
    _zone(timezone_name)

    schedule_time = schedule.get("time", payload.get("schedule_time", base.get("schedule_time")))
    schedule_weekday = schedule.get(
        "weekday", payload.get("schedule_weekday", base.get("schedule_weekday"))
    )
    schedule_minute = schedule.get(
        "minute", payload.get("schedule_minute", base.get("schedule_minute", 0))
    )

    if schedule_type in {"daily", "weekly"}:
        hour, minute = _parse_clock(schedule_time or "09:00")
        schedule_time = f"{hour:02d}:{minute:02d}"
    else:
        schedule_time = None

    if schedule_type == "weekly":
        try:
            schedule_weekday = int(0 if schedule_weekday is None else schedule_weekday)
        except (TypeError, ValueError) as exc:
            raise ValueError("schedule_weekday must be between 0 and 6") from exc
        if not 0 <= schedule_weekday <= 6:
            raise ValueError("schedule_weekday must be between 0 and 6")
    else:
        schedule_weekday = None

    if schedule_type == "hourly":
        try:
            schedule_minute = int(0 if schedule_minute is None else schedule_minute)
        except (TypeError, ValueError) as exc:
            raise ValueError("schedule_minute must be between 0 and 59") from exc
        if not 0 <= schedule_minute <= 59:
            raise ValueError("schedule_minute must be between 0 and 59")
    else:
        schedule_minute = None

    enabled = payload.get("enabled", base.get("enabled", True))
    enabled = bool(enabled)

    return {
        "name": name,
        "kind": kind,
        "prompt": prompt,
        "mode": mode,
        "workspace_id": workspace_id,
        "schedule_type": schedule_type,
        "schedule_time": schedule_time,
        "schedule_weekday": schedule_weekday,
        "schedule_minute": schedule_minute,
        "timezone": timezone_name,
        "enabled": enabled,
    }


def next_run_at(automation: dict, *, after: float | None = None) -> float | None:
    if not automation.get("enabled", True):
        return None
    schedule_type = str(automation.get("schedule_type") or "manual")
    if schedule_type == "manual":
        return None

    after_ts = _now() if after is None else float(after)
    zone = _zone(automation.get("timezone") or "UTC")
    current = datetime.fromtimestamp(after_ts, tz=timezone.utc).astimezone(zone)

    if schedule_type == "hourly":
        minute = int(automation.get("schedule_minute") or 0)
        candidate = current.replace(minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(hours=1)
    elif schedule_type == "daily":
        hour, minute = _parse_clock(automation.get("schedule_time") or "09:00")
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
    elif schedule_type == "weekly":
        hour, minute = _parse_clock(automation.get("schedule_time") or "09:00")
        weekday = int(automation.get("schedule_weekday") or 0)
        days = (weekday - current.weekday()) % 7
        candidate = (current + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= current:
            candidate += timedelta(days=7)
    else:
        raise ValueError("unsupported schedule type")

    return candidate.astimezone(timezone.utc).timestamp()


def _row_to_automation(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["schedule"] = {
        "type": item["schedule_type"],
        "time": item["schedule_time"],
        "weekday": item["schedule_weekday"],
        "minute": item["schedule_minute"],
        "timezone": item["timezone"],
    }
    return item


def _row_to_run(row) -> dict:
    item = dict(row)
    raw = item.pop("result_json", None)
    if raw:
        try:
            item["result"] = json.loads(raw)
        except json.JSONDecodeError:
            item["result"] = {"raw": raw}
    else:
        item["result"] = None
    return item


def list_automations() -> list[dict]:
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT * FROM automations ORDER BY enabled DESC, name COLLATE NOCASE, created_at"
        ).fetchall()
    return [_row_to_automation(row) for row in rows]


def get_automation(automation_id: str) -> dict | None:
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM automations WHERE id = ?", (str(automation_id),)
        ).fetchone()
    return _row_to_automation(row) if row else None


def create_automation(payload: dict) -> dict:
    values = normalize_payload(payload)
    now = _now()
    automation_id = uuid.uuid4().hex[:24]
    values["next_run_at"] = next_run_at(values, after=now)
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO automations (
                id, name, kind, prompt, mode, workspace_id, schedule_type,
                schedule_time, schedule_weekday, schedule_minute, timezone,
                enabled, next_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                automation_id, values["name"], values["kind"], values["prompt"],
                values["mode"], values["workspace_id"], values["schedule_type"],
                values["schedule_time"], values["schedule_weekday"],
                values["schedule_minute"], values["timezone"], int(values["enabled"]),
                values["next_run_at"], now, now,
            ),
        )
    return get_automation(automation_id)


def update_automation(automation_id: str, payload: dict) -> dict:
    current = get_automation(automation_id)
    if current is None:
        raise KeyError("automation not found")
    values = normalize_payload(payload, current=current)
    now = _now()
    values["next_run_at"] = next_run_at(values, after=now)
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            UPDATE automations
               SET name = ?, kind = ?, prompt = ?, mode = ?, workspace_id = ?,
                   schedule_type = ?, schedule_time = ?, schedule_weekday = ?,
                   schedule_minute = ?, timezone = ?, enabled = ?, next_run_at = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                values["name"], values["kind"], values["prompt"], values["mode"],
                values["workspace_id"], values["schedule_type"], values["schedule_time"],
                values["schedule_weekday"], values["schedule_minute"], values["timezone"],
                int(values["enabled"]), values["next_run_at"], now, str(automation_id),
            ),
        )
    return get_automation(automation_id)


def delete_automation(automation_id: str) -> bool:
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            "DELETE FROM automations WHERE id = ?", (str(automation_id),)
        )
        return cursor.rowcount > 0


def list_runs(*, automation_id: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        if automation_id:
            rows = connection.execute(
                "SELECT * FROM automation_runs WHERE automation_id = ? ORDER BY created_at DESC LIMIT ?",
                (str(automation_id), limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM automation_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_run(row) for row in rows]


def get_run(run_id: str) -> dict | None:
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM automation_runs WHERE id = ?", (str(run_id),)
        ).fetchone()
    return _row_to_run(row) if row else None


def _has_active_run(connection, automation_id: str) -> bool:
    placeholders = ",".join("?" for _ in ACTIVE_RUN_STATUSES)
    row = connection.execute(
        f"SELECT 1 FROM automation_runs WHERE automation_id = ? AND status IN ({placeholders}) LIMIT 1",
        (automation_id, *sorted(ACTIVE_RUN_STATUSES)),
    ).fetchone()
    return row is not None


def create_run(automation_id: str, *, trigger: str = "manual") -> dict:
    if trigger not in {"manual", "schedule"}:
        raise ValueError("unsupported trigger")
    run_id = uuid.uuid4().hex[:24]
    now = _now()
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        automation = connection.execute(
            "SELECT * FROM automations WHERE id = ?", (str(automation_id),)
        ).fetchone()
        if not automation:
            raise KeyError("automation not found")
        if _has_active_run(connection, str(automation_id)):
            raise RuntimeError("automation already running")
        connection.execute(
            """
            INSERT INTO automation_runs (id, automation_id, trigger, status, created_at)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (run_id, str(automation_id), trigger, now),
        )
        connection.execute(
            "UPDATE automations SET last_status = 'queued', updated_at = ? WHERE id = ?",
            (now, str(automation_id)),
        )
    return get_run(run_id)


def claim_due(*, now: float | None = None, limit: int = 4) -> list[dict]:
    now = _now() if now is None else float(now)
    limit = max(1, min(int(limit), 20))
    claimed = []
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT * FROM automations
             WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
             ORDER BY next_run_at ASC LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        for row in rows:
            automation = _row_to_automation(row)
            if _has_active_run(connection, automation["id"]):
                connection.execute(
                    "UPDATE automations SET next_run_at = ?, updated_at = ? WHERE id = ?",
                    (next_run_at(automation, after=now + 1), now, automation["id"]),
                )
                continue
            run_id = uuid.uuid4().hex[:24]
            connection.execute(
                """
                INSERT INTO automation_runs (id, automation_id, trigger, status, created_at)
                VALUES (?, ?, 'schedule', 'queued', ?)
                """,
                (run_id, automation["id"], now),
            )
            connection.execute(
                """
                UPDATE automations
                   SET next_run_at = ?, last_status = 'queued', updated_at = ?
                 WHERE id = ?
                """,
                (next_run_at(automation, after=now + 1), now, automation["id"]),
            )
            claimed.append({"run_id": run_id, "automation": automation})
        connection.commit()
    return claimed


def start_run(run_id: str) -> dict:
    now = _now()
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM automation_runs WHERE id = ?", (str(run_id),)
        ).fetchone()
        if not row:
            raise KeyError("run not found")
        if row["status"] != "queued":
            return _row_to_run(row)
        connection.execute(
            "UPDATE automation_runs SET status = 'running', started_at = ? WHERE id = ?",
            (now, str(run_id)),
        )
        connection.execute(
            "UPDATE automations SET last_run_at = ?, last_status = 'running', updated_at = ? WHERE id = ?",
            (now, now, row["automation_id"]),
        )
    return get_run(run_id)


def finish_run(run_id: str, *, status: str, result=None, error: str | None = None) -> dict:
    if status not in {"completed", "failed", "needs_approval", "cancelled"}:
        raise ValueError("unsupported terminal status")
    now = _now()
    raw_result = json.dumps(result, ensure_ascii=False) if result is not None else None
    with LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT automation_id FROM automation_runs WHERE id = ?", (str(run_id),)
        ).fetchone()
        if not row:
            raise KeyError("run not found")
        connection.execute(
            """
            UPDATE automation_runs
               SET status = ?, finished_at = ?, result_json = ?, error = ?
             WHERE id = ?
            """,
            (status, now, raw_result, str(error)[:4000] if error else None, str(run_id)),
        )
        connection.execute(
            "UPDATE automations SET last_status = ?, updated_at = ? WHERE id = ?",
            (status, now, row["automation_id"]),
        )
    return get_run(run_id)


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "AUTOMATIONS_DB",
    "LOCK",
    "claim_due",
    "create_automation",
    "create_run",
    "delete_automation",
    "finish_run",
    "get_automation",
    "get_run",
    "list_automations",
    "list_runs",
    "next_run_at",
    "normalize_payload",
    "start_run",
    "update_automation",
]
