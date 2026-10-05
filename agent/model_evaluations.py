"""Persistent local decisions from model benchmarks and manual evaluations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import uuid


EVALUATIONS_FILE = Path(
    os.environ.get(
        "MODEL_EVALUATIONS_FILE",
        str(Path.home() / ".config/mlx-web/model-evaluations.json"),
    )
).expanduser()
SCHEMA_VERSION = 1
MAX_EVALUATIONS = 250
VALID_STATUSES = {"keep", "rejected", "candidate", "tested", "superseded"}
VALID_KINDS = {
    "chat",
    "agent",
    "coding",
    "vision",
    "asr",
    "tts",
    "embedding",
    "image",
    "video",
    "router",
    "speculative",
    "other",
}


def _path(path: Path | str | None = None) -> Path:
    return Path(path).expanduser() if path is not None else EVALUATIONS_FILE


def _clean_text(value, *, field: str, required: bool = False, max_length: int = 2000) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    text = str(value).strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field} is too long")
    return text


def _clean_metrics(metrics: dict | None) -> dict:
    if metrics is None:
        return {}
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be an object")
    cleaned = {}
    for raw_key, value in metrics.items():
        key = str(raw_key).strip()
        if not key or len(key) > 120 or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            raise ValueError(f"invalid metric name: {raw_key}")
        if value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            raise ValueError(f"metric {key} must be a scalar value")
    return cleaned


def _normalize_record(record: dict) -> dict | None:
    if not isinstance(record, dict):
        return None
    try:
        model = _clean_text(record.get("model"), field="model", required=True, max_length=500)
        kind = _clean_text(record.get("kind"), field="kind", required=True, max_length=40)
        status = _clean_text(record.get("status"), field="status", required=True, max_length=40)
        reason = _clean_text(record.get("reason"), field="reason", required=True)
        if kind not in VALID_KINDS or status not in VALID_STATUSES:
            return None
        metrics = _clean_metrics(record.get("metrics") or {})
    except ValueError:
        return None
    created_at = str(record.get("created_at") or "").strip()
    if not created_at:
        created_at = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(record.get("id") or uuid.uuid4().hex[:12]),
        "model": model,
        "kind": kind,
        "status": status,
        "reason": reason,
        "compared_to": _clean_text(record.get("compared_to"), field="compared_to", max_length=500),
        "metrics": metrics,
        "source": _clean_text(record.get("source"), field="source", max_length=120) or "manual",
        "created_at": created_at,
    }


def load(path: Path | str | None = None) -> list[dict]:
    target = _path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        records = payload.get("evaluations")
    else:
        records = payload
    if not isinstance(records, list):
        return []
    normalized = []
    for item in records:
        record = _normalize_record(item)
        if record is not None:
            normalized.append(record)
    return normalized[:MAX_EVALUATIONS]


def _write(records: list[dict], path: Path | str | None = None) -> None:
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "evaluations": records[:MAX_EVALUATIONS],
    }
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def record(
    model: str,
    *,
    kind: str,
    status: str,
    reason: str,
    metrics: dict | None = None,
    compared_to: str | None = None,
    source: str = "manual",
    path: Path | str | None = None,
) -> dict:
    model = _clean_text(model, field="model", required=True, max_length=500)
    kind = _clean_text(kind, field="kind", required=True, max_length=40)
    status = _clean_text(status, field="status", required=True, max_length=40)
    reason = _clean_text(reason, field="reason", required=True)
    if kind not in VALID_KINDS:
        raise ValueError(f"unsupported evaluation kind: {kind}")
    if status not in VALID_STATUSES:
        raise ValueError(f"unsupported evaluation status: {status}")
    evaluation = {
        "id": uuid.uuid4().hex[:12],
        "model": model,
        "kind": kind,
        "status": status,
        "reason": reason,
        "compared_to": _clean_text(compared_to, field="compared_to", max_length=500),
        "metrics": _clean_metrics(metrics),
        "source": _clean_text(source, field="source", max_length=120) or "manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    records = [evaluation, *load(path)]
    _write(records, path)
    return evaluation


def latest(model: str, *, kind: str | None = None, path: Path | str | None = None) -> dict | None:
    target_model = str(model or "").strip().casefold()
    target_kind = str(kind or "").strip().casefold() or None
    for evaluation in load(path):
        if evaluation["model"].casefold() != target_model:
            continue
        if target_kind is not None and evaluation["kind"].casefold() != target_kind:
            continue
        return evaluation
    return None


def list_latest(
    *,
    kind: str | None = None,
    status: str | None = None,
    path: Path | str | None = None,
) -> list[dict]:
    target_kind = str(kind or "").strip().casefold() or None
    target_status = str(status or "").strip().casefold() or None
    seen = set()
    results = []
    for evaluation in load(path):
        key = (evaluation["model"].casefold(), evaluation["kind"].casefold())
        if key in seen:
            continue
        seen.add(key)
        if target_kind is not None and key[1] != target_kind:
            continue
        if target_status is not None and evaluation["status"].casefold() != target_status:
            continue
        results.append(evaluation)
    return results


def is_rejected(model: str, *, kind: str | None = None, path: Path | str | None = None) -> bool:
    evaluation = latest(model, kind=kind, path=path)
    return bool(evaluation and evaluation.get("status") == "rejected")


__all__ = [
    "EVALUATIONS_FILE",
    "MAX_EVALUATIONS",
    "SCHEMA_VERSION",
    "VALID_KINDS",
    "VALID_STATUSES",
    "is_rejected",
    "latest",
    "list_latest",
    "load",
    "record",
]
