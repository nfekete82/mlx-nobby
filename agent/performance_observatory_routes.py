"""Performance Observatory v2 for local model, media, and memory metrics."""

from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import socket
import time
import urllib.parse

from fastapi import FastAPI

from agent import media_queue
from backend import observability
import runtime_coordinator


DEFAULT_LIMIT = 40
MAX_LIMIT = 100
HANDOFF_STAGE_KEYS = (
    "lease_wait", "image_release", "speech_release",
    "musetalk_release", "chat_stop",
)
LTX_URL = os.environ.get("LTX_URL", "http://127.0.0.1:18060").rstrip("/")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _rounded(value, digits=2):
    value = _number(value)
    return None if value is None else round(value, digits)


def _limit(value, default=DEFAULT_LIMIT):
    try:
        return max(1, min(MAX_LIMIT, int(value)))
    except (TypeError, ValueError):
        return default


def _percentile(values, fraction):
    clean = sorted(
        value for value in (_number(item) for item in values) if value is not None
    )
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = max(0.0, min(1.0, float(fraction))) * (len(clean) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return clean[lower]
    weight = position - lower
    return clean[lower] + (clean[upper] - clean[lower]) * weight


def metric_series(values):
    clean = [
        value for value in (_number(item) for item in values) if value is not None
    ]
    if not clean:
        return {
            "count": 0,
            "latest": None,
            "average": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(clean),
        "latest": _rounded(clean[-1]),
        "average": _rounded(sum(clean) / len(clean)),
        "p50": _rounded(_percentile(clean, 0.50)),
        "p95": _rounded(_percentile(clean, 0.95)),
        "min": _rounded(min(clean)),
        "max": _rounded(max(clean)),
    }


def _safe_model_identifier(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("/", "~")):
        return Path(text).name
    return text[:160]


def _model_calls(limit=DEFAULT_LIMIT):
    """Return recent content-free model-call measurements from observability."""
    limit = _limit(limit)

    with observability._TRACE_LOCK:
        traces = deepcopy(list(observability._TRACES.items()))

    calls = []
    sequence = 0
    for trace_id, trace in traces:
        for raw in trace.get("calls") or []:
            sequence += 1
            timings = raw.get("timings_ms") if isinstance(raw, dict) else {}
            timings = timings if isinstance(timings, dict) else {}
            usage = raw.get("usage") if isinstance(raw, dict) else {}
            usage = usage if isinstance(usage, dict) else {}
            model = raw.get("model") if isinstance(raw, dict) else {}
            model = model if isinstance(model, dict) else {}

            generation_ms = _number(timings.get("generation"))
            output_tokens = _number(usage.get("output_tokens"))
            tokens_per_second = None
            if generation_ms and generation_ms > 0 and output_tokens is not None:
                tokens_per_second = output_tokens / (generation_ms / 1000.0)

            calls.append({
                "sequence": sequence,
                "trace_id": str(trace_id),
                "request_id": raw.get("request_id"),
                "purpose": str(raw.get("purpose") or "model_call")[:120],
                "status": str(raw.get("status") or "unknown")[:40],
                "model": {
                    "identifier": _safe_model_identifier(model.get("identifier")),
                    "role": str(model.get("role") or "")[:80] or None,
                    "backend": str(model.get("backend") or "")[:80] or None,
                    "local": bool(model.get("local")),
                },
                "timings_ms": {
                    "total": _rounded(timings.get("total"), 3),
                    "queue_wait": _rounded(timings.get("queue_wait"), 3),
                    "upstream_connect": _rounded(timings.get("upstream_connect"), 3),
                    "ttft": _rounded(timings.get("ttft"), 3),
                    "generation": _rounded(generation_ms, 3),
                },
                "usage": {
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "count_method": str(usage.get("count_method") or "unknown")[:40],
                },
                "tokens_per_second": _rounded(tokens_per_second),
                "finish_reason": raw.get("finish_reason"),
            })

    calls.sort(key=lambda item: item["sequence"], reverse=True)
    return calls[:limit]


def model_performance_snapshot(limit=DEFAULT_LIMIT):
    calls = _model_calls(limit)
    chronological = list(reversed(calls))
    completed = [call for call in chronological if call["status"] == "completed"]
    chat_calls = [
        call for call in completed
        if call["purpose"].startswith("chat.")
        and (
            call["timings_ms"].get("ttft") is not None
            or call.get("tokens_per_second") is not None
        )
    ]
    measured = chat_calls or [
        call for call in completed
        if call["timings_ms"].get("ttft") is not None
        or call.get("tokens_per_second") is not None
    ]

    return {
        "summary": {
            "calls": len(calls),
            "completed": len(completed),
            "failed": sum(call["status"] == "failed" for call in calls),
            "ttft_ms": metric_series(
                call["timings_ms"].get("ttft") for call in measured
            ),
            "tokens_per_second": metric_series(
                call.get("tokens_per_second") for call in measured
            ),
            "total_ms": metric_series(
                call["timings_ms"].get("total") for call in measured
            ),
        },
        "recent_calls": calls,
    }


def _duration_ms(start, finish):
    start = _number(start)
    finish = _number(finish)
    if start is None or finish is None or finish < start:
        return None
    return round((finish - start) * 1000.0, 2)


def _runtime_reuse(raw):
    result = raw.get("result") if isinstance(raw, dict) else None
    result = result if isinstance(result, dict) else {}
    value = result.get("runtime_reused")
    if isinstance(value, bool):
        return "warm" if value else "cold"
    return None


def media_performance_snapshot(queue_snapshot=None, limit=DEFAULT_LIMIT):
    limit = _limit(limit)
    snapshot = queue_snapshot if isinstance(queue_snapshot, dict) else media_queue.snapshot(limit=100)
    raw_jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []

    jobs = []
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        created = raw.get("created_at")
        started = raw.get("started_at")
        finished = raw.get("finished_at")
        handoff = raw.get("runtime_handoff")
        handoff = handoff if isinstance(handoff, dict) else {}
        handoff_value = _number(handoff.get("duration_ms"))
        handoff_ms = (
            _rounded(handoff_value)
            if handoff_value is not None and handoff_value >= 0
            else None
        )
        stages = handoff.get("timings_ms")
        stages = stages if isinstance(stages, dict) else {}
        stage_timings = {}
        for key in HANDOFF_STAGE_KEYS:
            value = _number(stages.get(key))
            stage_timings[key] = (
                _rounded(value)
                if value is not None and value >= 0
                else None
            )
        # Previous persisted jobs used the wrong image release predicate:
        # an image runtime that was already cold counted as "released".
        # Only the corrected V2 producer can supply a reliable answer.
        handoff_version = handoff.get("version")
        verified_image_release = (
            handoff.get("image_released")
            if type(handoff_version) is int and handoff_version >= 2
            and type(handoff.get("image_released")) is bool
            else None
        )
        jobs.append({
            "id": str(raw.get("id") or "")[:64],
            "kind": str(raw.get("kind") or "media")[:24],
            "status": str(raw.get("status") or "unknown")[:40],
            "phase": str(raw.get("phase") or "")[:80] or None,
            "model": _safe_model_identifier(raw.get("model")),
            "runtime_start": _runtime_reuse(raw),
            "handoff_ms": handoff_ms,
            "handoff_stages_ms": stage_timings,
            "image_released": verified_image_release,
            "chat_released": (
                handoff.get("chat_released")
                if type(handoff.get("chat_released")) is bool
                else None
            ),
            "queue_wait_ms": _duration_ms(created, started),
            "generation_ms": _duration_ms(started, finished),
            "total_ms": _duration_ms(created, finished),
            "created_at": _rounded(created, 3),
            "finished_at": _rounded(finished, 3),
        })

    terminal = {"completed", "failed", "cancelled"}
    jobs.sort(
        key=lambda item: (
            0 if item.get("status") not in terminal else 1,
            -float(item.get("finished_at") or item.get("created_at") or 0),
        )
    )
    recent = jobs[:limit]
    completed = [job for job in jobs if job["status"] == "completed"]

    kinds = {}
    for kind in ("image", "video", "shorts"):
        selected = [job for job in completed if job["kind"] == kind]
        kinds[kind] = {
            "count": len(selected),
            "generation_ms": metric_series(job.get("generation_ms") for job in selected),
            "queue_wait_ms": metric_series(job.get("queue_wait_ms") for job in selected),
            "total_ms": metric_series(job.get("total_ms") for job in selected),
            "warm_starts": sum(job.get("runtime_start") == "warm" for job in selected),
            "cold_starts": sum(job.get("runtime_start") == "cold" for job in selected),
            "handoff_ms": metric_series(job.get("handoff_ms") for job in selected),
            "handoff_stages_ms": {
                key: metric_series(
                    job.get("handoff_stages_ms", {}).get(key)
                    for job in selected
                )
                for key in HANDOFF_STAGE_KEYS
            },
            "image_releases": sum(job.get("image_released") is True for job in selected),
            "image_release_samples": sum(job.get("image_released") is not None for job in selected),
            "chat_releases": sum(job.get("chat_released") is True for job in selected),
        }

    return {
        "summary": kinds,
        "recent_jobs": recent,
        "active_count": int(snapshot.get("active_count") or 0),
        "waiting_count": int(snapshot.get("waiting_count") or 0),
    }


def _service_health(url):
    try:
        value = runtime_coordinator.request_json("GET", url + "/health", timeout=3)
    except Exception as exc:
        return {
            "available": False,
            "loaded": False,
            "active": False,
            "detail": str(exc)[:240],
        }
    if not isinstance(value, dict):
        value = {}
    nested = value.get("warm_runtime") if isinstance(value.get("warm_runtime"), dict) else {}
    loaded = bool(
        value.get("loaded")
        or value.get("runtime_loaded")
        or nested.get("loaded")
    )
    active = bool(
        value.get("active_generation")
        or value.get("busy")
        or value.get("status") == "busy"
    )
    return {
        "available": True,
        "loaded": loaded,
        "active": active,
        "model": _safe_model_identifier(
            value.get("model")
            or value.get("current_model")
            or value.get("running_model")
            or value.get("runtime_model")
            or nested.get("model")
        ),
        "detail": None,
    }


def _ltx_runtime_loaded():
    """Detect the video worker without relying on process-local provider state."""
    try:
        parsed = urllib.parse.urlsplit(LTX_URL)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 18060
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except (OSError, ValueError):
        return False


def runtime_snapshot(status_provider=None):
    try:
        chat = status_provider() if callable(status_provider) else {}
    except Exception as exc:
        chat = {"online": False, "error": str(exc)}
    chat = chat if isinstance(chat, dict) else {}

    image = _service_health(runtime_coordinator.IMAGE_URL)
    video = _service_health(runtime_coordinator.VIDEO_URL)
    if video.get("available"):
        video["loaded"] = bool(video.get("loaded") or _ltx_runtime_loaded())

    return {
        "chat": {
            "available": bool(chat.get("online")),
            "loaded": bool(chat.get("online")),
            "active": bool(chat.get("busy") or chat.get("active_generation")),
            "model": _safe_model_identifier(chat.get("model")),
            "state": "warm" if chat.get("online") else "cold",
        },
        "image": image,
        "video": video,
    }


def _normalize_runtime_states(runtimes):
    for value in runtimes.values():
        if "state" not in value:
            value["state"] = (
                "unavailable"
                if not value.get("available")
                else "warm" if value.get("loaded") else "cold"
            )
    return runtimes


def build_performance_snapshot(status_provider=None, limit=DEFAULT_LIMIT):
    limit = _limit(limit)

    queue_snapshot = media_queue.snapshot(limit=100)
    # The queue already captures the coordinator's diagnostic memory view.
    # Reuse it rather than launching a second memory_pressure/sysctl sweep.
    runtime_state = queue_snapshot.get("runtime")
    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    memory = runtime_state.get("memory")
    if not isinstance(memory, dict):
        memory = runtime_coordinator.memory_budget_snapshot()

    return {
        "ok": True,
        "version": 2,
        "captured_at": time.time(),
        "model": model_performance_snapshot(limit),
        "media": media_performance_snapshot(queue_snapshot, limit),
        "system": {
            "memory": memory,
            "runtimes": _normalize_runtime_states(runtime_snapshot(status_provider)),
            "runtime_lease": queue_snapshot.get("runtime") or {},
        },
        "notes": {
            "model_history": "in-memory since the current Agent process started",
            "media_history": "durable media queue history",
            "runtime_state": "live loaded/unloaded state; video jobs also expose historical warm/cold reuse when available",
        },
    }


def install_routes(app: FastAPI, *, status_provider=None) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}
    if "/api/performance/observatory" in paths:
        return

    @app.get("/api/performance/observatory")
    def performance_observatory(limit: int = DEFAULT_LIMIT):
        return build_performance_snapshot(status_provider, limit)


__all__ = [
    "build_performance_snapshot",
    "install_routes",
    "media_performance_snapshot",
    "metric_series",
    "model_performance_snapshot",
    "runtime_snapshot",
]
