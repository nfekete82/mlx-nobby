"""Local request tracing and model-call metrics without content retention."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid


TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
CONTEXT_SOURCES = (
    "system",
    "profile",
    "history",
    "knowledge_rag",
    "document_web",
    "attachments",
    "tool_agent",
)
MAX_RETAINED_TRACES = 256
MAX_RETAINED_CALLS_PER_TRACE = 512

_CURRENT_TRACE_ID = ContextVar("mlx_trace_id", default=None)
_CURRENT_PARENT_REQUEST_ID = ContextVar(
    "mlx_parent_request_id",
    default=None,
)
_CURRENT_CALL_PURPOSE = ContextVar("mlx_call_purpose", default=None)
_CURRENT_CONTEXT_SOURCES = ContextVar("mlx_context_sources", default=None)
_TRACE_LOCK = threading.RLock()
_TRACES = OrderedDict()


def new_trace_id():
    return uuid.uuid4().hex


def ensure_trace_id(value=None):
    candidate = str(value or "").strip()
    return candidate if TRACE_ID_PATTERN.fullmatch(candidate) else new_trace_id()


def current_trace_id():
    return _CURRENT_TRACE_ID.get()


def current_call_purpose(default="model_call"):
    return _CURRENT_CALL_PURPOSE.get() or default


def current_context_sources(default=None):
    return _CURRENT_CONTEXT_SOURCES.get() or default


def bind_trace_id(trace_id=None):
    """Bind a trace in a worker thread and return its reset token."""
    return _CURRENT_TRACE_ID.set(ensure_trace_id(trace_id))


def reset_trace_id(token):
    _CURRENT_TRACE_ID.reset(token)


@contextmanager
def trace_context(trace_id=None, parent_request_id=None):
    resolved = ensure_trace_id(trace_id or current_trace_id())
    trace_token = _CURRENT_TRACE_ID.set(resolved)
    parent_token = _CURRENT_PARENT_REQUEST_ID.set(parent_request_id)
    try:
        yield resolved
    finally:
        _CURRENT_PARENT_REQUEST_ID.reset(parent_token)
        _CURRENT_TRACE_ID.reset(trace_token)


@contextmanager
def model_call_context(purpose, context_sources=None, parent_request_id=None):
    purpose_token = _CURRENT_CALL_PURPOSE.set(str(purpose or "model_call"))
    context_token = _CURRENT_CONTEXT_SOURCES.set(context_sources)
    parent_token = _CURRENT_PARENT_REQUEST_ID.set(parent_request_id)
    try:
        yield
    finally:
        _CURRENT_PARENT_REQUEST_ID.reset(parent_token)
        _CURRENT_CONTEXT_SOURCES.reset(context_token)
        _CURRENT_CALL_PURPOSE.reset(purpose_token)


def observed_turn(function):
    """Bind a request trace and add safe metrics to dictionary responses."""
    @wraps(function)
    def wrapped(request, *args, **kwargs):
        with trace_context(getattr(request, "trace_id", None)) as trace_id:
            result = function(request, *args, **kwargs)
            if isinstance(result, dict):
                result.setdefault("trace_id", trace_id)
                result["model_metrics"] = trace_snapshot(trace_id)
            return result

    return wrapped


def estimate_tokens_from_characters(characters):
    value = max(0, int(characters or 0))
    return 0 if value == 0 else max(1, (value + 3) // 4)


def text_characters(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(text_characters(item) for item in value)
    if isinstance(value, dict):
        return sum(
            text_characters(item)
            for key, item in value.items()
            if key not in {"image_url", "url", "data_url"}
        )
    return 0


def estimate_message_tokens(messages):
    return estimate_tokens_from_characters(text_characters(messages))


def message_context_counts(messages, content_source="history"):
    counts = {
        "system": {"characters": 0, "items": 0},
        content_source: {"characters": 0, "items": 0},
    }
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        source = "system" if message.get("role") == "system" else content_source
        characters = text_characters(message.get("content"))
        counts[source]["characters"] += characters
        counts[source]["items"] += 1
    return counts


def context_accounting(source_counts=None):
    raw = source_counts if isinstance(source_counts, dict) else {}
    entries = []

    for source in CONTEXT_SOURCES:
        value = raw.get(source, 0)
        if isinstance(value, dict):
            characters = value.get("characters", 0)
            items = value.get("items", 0)
        else:
            characters = value
            items = 0

        try:
            characters = max(0, int(characters or 0))
        except (TypeError, ValueError):
            characters = 0
        try:
            items = max(0, int(items or 0))
        except (TypeError, ValueError):
            items = 0

        entries.append({
            "source": source,
            "characters": characters,
            "items": items,
            "estimated_tokens": estimate_tokens_from_characters(characters),
            "count_method": "estimate",
        })

    return entries


def safe_model_metadata(model=None, role=None, alias=None, backend=None):
    value = str(model or "").strip()
    metadata = {
        "role": str(role or "").strip() or None,
        "alias": str(alias or "").strip() or None,
        "backend": str(backend or "").strip() or None,
        "identifier": None,
        "identifier_hash": None,
        "local": False,
    }

    if value:
        is_local = value.startswith(("/", "~"))
        metadata["local"] = is_local
        metadata["identifier"] = Path(value).name if is_local else value
        metadata["identifier_hash"] = hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:16]

    return metadata


def normalize_usage(
    usage,
    input_estimate=0,
    output_text="",
    output_characters=None,
    reasoning_characters=0,
):
    raw = usage if isinstance(usage, dict) else {}
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens"))
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens"))
    total_tokens = raw.get("total_tokens")
    details = raw.get("completion_tokens_details")
    reasoning_tokens = raw.get("reasoning_tokens")

    if reasoning_tokens is None and isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")

    supplied = any(
        value is not None
        for value in (input_tokens, output_tokens, total_tokens, reasoning_tokens)
    )

    def integer(value, fallback=0):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return max(0, int(fallback or 0))

    if supplied:
        input_tokens = integer(input_tokens)
        output_tokens = integer(output_tokens)
        reasoning_tokens = integer(reasoning_tokens)
        total_tokens = integer(
            total_tokens,
            input_tokens + output_tokens,
        )
        method = "upstream"
    else:
        input_tokens = integer(input_estimate)
        content_characters = (
            len(str(output_text or ""))
            if output_characters is None
            else integer(output_characters)
        )
        reasoning_tokens = estimate_tokens_from_characters(
            reasoning_characters
        )
        output_tokens = estimate_tokens_from_characters(
            content_characters + integer(reasoning_characters)
        )
        total_tokens = input_tokens + output_tokens
        method = "estimate"

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "count_method": method,
    }


class ModelCallMetrics:
    def __init__(
        self,
        *,
        trace_id=None,
        parent_request_id=None,
        purpose,
        model=None,
        role=None,
        alias=None,
        backend=None,
        messages=None,
        context_sources=None,
        started_at=None,
    ):
        self.started = (
            float(started_at)
            if started_at is not None
            else time.monotonic()
        )
        self.first_token_at = None
        self.upstream_connected_at = None
        self.trace_id = ensure_trace_id(trace_id or current_trace_id())
        self.request_id = uuid.uuid4().hex
        self.input_estimate = estimate_message_tokens(messages or [])
        self.metric = {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "parent_request_id": (
                parent_request_id or _CURRENT_PARENT_REQUEST_ID.get()
            ),
            "purpose": str(purpose or "model_call"),
            "status": "running",
            "model_call_index": 0,
            "model_calls_in_turn": 0,
            "model": safe_model_metadata(
                model=model,
                role=role,
                alias=alias,
                backend=backend,
            ),
            "timings_ms": {
                "total": None,
                "queue_wait": None,
                "upstream_connect": None,
                "ttft": None,
                "generation": None,
            },
            "finish_reason": None,
            "usage": normalize_usage(None, self.input_estimate),
            "context": context_accounting(context_sources),
        }

        with _TRACE_LOCK:
            trace = _TRACES.setdefault(
                self.trace_id,
                {"total_calls": 0, "calls": []},
            )
            calls = trace["calls"]
            if self.metric["parent_request_id"] is None and calls:
                self.metric["parent_request_id"] = calls[-1]["request_id"]
            trace["total_calls"] += 1
            calls.append(self.metric)
            self.metric["model_call_index"] = trace["total_calls"]
            if len(calls) > MAX_RETAINED_CALLS_PER_TRACE:
                del calls[:-MAX_RETAINED_CALLS_PER_TRACE]
            _TRACES.move_to_end(self.trace_id)
            while len(_TRACES) > MAX_RETAINED_TRACES:
                _TRACES.popitem(last=False)

    def set_queue_wait(self, milliseconds):
        with _TRACE_LOCK:
            self.metric["timings_ms"]["queue_wait"] = max(
                0,
                round(float(milliseconds), 3),
            )

    def set_model(self, model=None, role=None, alias=None, backend=None):
        with _TRACE_LOCK:
            self.metric["model"] = safe_model_metadata(
                model=model,
                role=role,
                alias=alias,
                backend=backend,
            )

    def set_upstream_connect(self, milliseconds):
        self.upstream_connected_at = time.monotonic()
        with _TRACE_LOCK:
            self.metric["timings_ms"]["upstream_connect"] = max(
                0,
                round(float(milliseconds), 3),
            )

    def mark_first_token(self):
        if self.first_token_at is not None:
            return
        self.first_token_at = time.monotonic()
        with _TRACE_LOCK:
            self.metric["timings_ms"]["ttft"] = round(
                (self.first_token_at - self.started) * 1000,
                3,
            )

    def finish(
        self,
        *,
        usage=None,
        output_text="",
        output_characters=None,
        reasoning_characters=0,
        finish_reason=None,
    ):
        finished = time.monotonic()
        with _TRACE_LOCK:
            self.metric["status"] = "completed"
            self.metric["finish_reason"] = finish_reason
            self.metric["timings_ms"]["total"] = round(
                (finished - self.started) * 1000,
                3,
            )
            if self.first_token_at is not None:
                self.metric["timings_ms"]["generation"] = round(
                    (finished - self.first_token_at) * 1000,
                    3,
                )
            elif self.upstream_connected_at is not None:
                self.metric["timings_ms"]["generation"] = round(
                    (finished - self.upstream_connected_at) * 1000,
                    3,
                )
            self.metric["usage"] = normalize_usage(
                usage,
                self.input_estimate,
                output_text,
                output_characters,
                reasoning_characters,
            )
        return self.metric

    def fail(self, error_type=None):
        with _TRACE_LOCK:
            self.metric["status"] = "failed"
            self.metric["error_type"] = str(
                error_type or "model_call_failed"
            )[:120]
            self.metric["timings_ms"]["total"] = round(
                (time.monotonic() - self.started) * 1000,
                3,
            )
        return self.metric


def trace_snapshot(trace_id):
    resolved = ensure_trace_id(trace_id)
    with _TRACE_LOCK:
        trace = deepcopy(_TRACES.get(
            resolved,
            {"total_calls": 0, "calls": []},
        ))
    calls = trace["calls"]
    count = trace["total_calls"]
    for call in calls:
        call["model_calls_in_turn"] = count
    return {
        "trace_id": resolved,
        "model_calls_in_turn": count,
        "calls_retained": len(calls),
        "calls_truncated": max(0, count - len(calls)),
        "calls": calls,
    }


def metrics_sse(trace_id):
    return (
        "event: metrics\n"
        "data: "
        + json.dumps(trace_snapshot(trace_id), ensure_ascii=False)
        + "\n\n"
    )


def reset_metrics():
    """Clear in-memory metrics for isolated tests."""
    with _TRACE_LOCK:
        _TRACES.clear()
