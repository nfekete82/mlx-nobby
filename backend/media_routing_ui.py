"""Media-routing UI helpers, conservative route guard and local observatory."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from backend.media_intent import decide_media_intent, has_image_context


MEDIA_ROUTING_SCRIPT = (
    b'<script src="/assets/chat/media-routing-fallback.js?v=20260929-chat-fallback-v1"></script>'
)
ROUTING_OBSERVATORY_ASSETS = (
    b'<link rel="stylesheet" href="/assets/chat/routing-observatory.css?v=20260930-routing-v1">\n'
    + MEDIA_ROUTING_SCRIPT
    + b'\n<script src="/assets/chat/routing-observatory.js?v=20260930-routing-v1"></script>'
)
MEDIA_ROUTE_PATH = "/api/mlx/chat/actions/route"
ROUTING_DECISION_LIMIT = 500
ROUTING_OBSERVATORY_FILE = Path(
    os.environ.get(
        "MLX_ROUTING_OBSERVATORY_FILE",
        str(Path.home() / ".config/mlx-web/routing-observatory.json"),
    )
)
ROUTING_OBSERVATORY_LOCK = threading.RLock()

ACTIVE_MEDIA_TARGETS = {
    "image",
    "image_edit",
    "shorts_generate",
    "video",
    "video_generate",
    "video_animate",
}
FEEDBACK_TARGETS = {
    "chat",
    "image",
    "video_generate",
    "shorts_generate",
    "agent",
    "web_search",
}

def _is_chat_html_path(path: str) -> bool:
    return path in {"/", "/chat", "/settings"} or path.startswith("/settings/")


def inject_media_routing_script(body: bytes) -> bytes:
    if ROUTING_OBSERVATORY_ASSETS in body:
        return body

    marker = b"</body>"
    if marker in body:
        return body.replace(marker, ROUTING_OBSERVATORY_ASSETS + b"\n" + marker, 1)

    return body


def _explicit_intent(prompt, target, action=None):
    decision = decide_media_intent(prompt, has_image=target == "image_edit", action=action)
    return decision.execution_requested and decision.target == target


def conservative_media_target(prompt: str, target: str) -> str:
    """Media requires explicit execution, irrespective of model confidence."""
    if target not in ACTIVE_MEDIA_TARGETS:
        return target
    decision = decide_media_intent(prompt, has_image=target == "image_edit")
    return decision.target if decision.execution_requested else "chat"


def _normalized_prompt_preview(prompt: str, limit: int = 220) -> str:
    """Compatibility helper: raw text is never an observatory preview."""
    return "[redacted]"


def _empty_store() -> dict:
    return {"version": 1, "decisions": []}


def _read_observatory_store() -> dict:
    if not ROUTING_OBSERVATORY_FILE.exists():
        return _empty_store()

    try:
        payload = json.loads(ROUTING_OBSERVATORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()

    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list):
        return _empty_store()

    sanitized = []
    for item in decisions[-ROUTING_DECISION_LIMIT:]:
        if isinstance(item, dict):
            safe = dict(item)
            safe["prompt_preview"] = "[redacted]"
            safe.pop("prompt", None)
            safe.pop("file_context", None)
            sanitized.append(safe)
    return {"version": 1, "decisions": sanitized}


def _write_observatory_store(payload: dict) -> None:
    ROUTING_OBSERVATORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ROUTING_OBSERVATORY_FILE.with_name(
        f".{ROUTING_OBSERVATORY_FILE.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, ROUTING_OBSERVATORY_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def record_routing_decision(decision: dict) -> dict:
    record = dict(decision)
    record["prompt_preview"] = "[redacted]"
    record.pop("prompt", None)
    record.pop("file_context", None)
    record.setdefault("id", uuid.uuid4().hex)
    record.setdefault("created_at", time.time())

    with ROUTING_OBSERVATORY_LOCK:
        payload = _read_observatory_store()
        payload["decisions"].append(record)
        payload["decisions"] = payload["decisions"][-ROUTING_DECISION_LIMIT:]
        _write_observatory_store(payload)

    return record


def list_routing_decisions(limit: int = 50) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    with ROUTING_OBSERVATORY_LOCK:
        decisions = _read_observatory_store()["decisions"]
    return list(reversed(decisions[-safe_limit:]))


def save_routing_feedback(
    decision_id: str,
    correct: bool,
    expected_target: str | None = None,
) -> dict:
    if not isinstance(correct, bool):
        raise HTTPException(400, "correct muss true oder false sein.")

    if correct:
        expected_target = None
    elif expected_target not in FEEDBACK_TARGETS:
        raise HTTPException(400, "Ungültige Zielroute für Routing-Feedback.")

    with ROUTING_OBSERVATORY_LOCK:
        payload = _read_observatory_store()
        for decision in payload["decisions"]:
            if decision.get("id") != decision_id:
                continue

            decision["feedback"] = {
                "correct": correct,
                "expected_target": expected_target,
                "updated_at": time.time(),
            }
            decision["regression_candidate"] = not correct
            _write_observatory_store(payload)
            return decision

    raise HTTPException(404, "Routing-Entscheidung nicht gefunden.")


def list_regression_candidates() -> list[dict]:
    with ROUTING_OBSERVATORY_LOCK:
        decisions = _read_observatory_store()["decisions"]

    return [
        decision
        for decision in reversed(decisions)
        if decision.get("regression_candidate") is True
    ]


def guard_media_route_payload(
    request_body: bytes,
    response_body: bytes,
    *,
    duration_ms: float | None = None,
    record: bool = False,
) -> bytes:
    """Guard route responses and optionally persist an observability trace."""
    try:
        request_payload = json.loads(request_body.decode("utf-8"))
        response_payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return response_body

    if not isinstance(request_payload, dict) or not isinstance(response_payload, dict):
        return response_body

    prompt = str(request_payload.get("prompt") or "")
    action = str(request_payload.get("action") or "") or None
    original_target = str(response_payload.get("target") or "")
    has_image = has_image_context(request_payload.get("file_context"), request_payload.get("active_artifact_id"))
    media = decide_media_intent(prompt, has_image=has_image, action=action)
    guarded_target = original_target
    reason = None
    if original_target in ACTIVE_MEDIA_TARGETS or media.handles_turn:
        guarded_target = media.target
        if guarded_target != original_target:
            reason = media.guard or "central_media_intent"
    if original_target in ACTIVE_MEDIA_TARGETS or media.handles_turn:
        response_payload.update(media.payload() | {"target": guarded_target})
    else:
        response_payload.setdefault("execution_requested", False)
        response_payload.setdefault("media_context", media.media_context)

    if guarded_target != original_target:
        response_payload["target"] = guarded_target
        response_payload["routing_guard"] = reason or "confidence_fallback"

    decision_id = uuid.uuid4().hex
    trace = {
        "id": decision_id,
        "created_at": time.time(),
        "prompt_preview": "[redacted]",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_chars": len(prompt),
        "intent": response_payload.get("intent", media.intent),
        "execution_requested": media.execution_requested,
        "media_context": media.media_context,
        "guard": media.guard,
        "original_target": original_target,
        "target": guarded_target,
        "confidence": media.confidence,
        "confidence_source": "central_media_intent",
        "reason": reason or media.reason,
        "guarded": guarded_target != original_target,
        "fallback": guarded_target if guarded_target != original_target else None,
        "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
    }

    response_payload["routing_observatory"] = {
        "id": decision_id,
        "original_target": original_target,
        "target": guarded_target,
        "confidence": media.confidence,
        "confidence_source": "central_media_intent",
        "reason": trace["reason"],
        "guarded": trace["guarded"],
    }

    if record:
        try:
            record_routing_decision(trace)
        except (OSError, TypeError, ValueError):
            # Observability must never block a chat/media route.
            pass

    return json.dumps(
        response_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def install_routes(app) -> None:
    @app.get("/api/routing/decisions")
    def routing_decisions(limit: int = 50):
        return {
            "decisions": list_routing_decisions(limit),
            "max_retained": ROUTING_DECISION_LIMIT,
        }

    @app.post("/api/routing/decisions/{decision_id}/feedback")
    def routing_feedback(decision_id: str, request: dict):
        return save_routing_feedback(
            decision_id,
            request.get("correct"),
            request.get("expected_target"),
        )

    @app.get("/api/routing/regressions")
    def routing_regressions():
        return {"candidates": list_regression_candidates()}


class MediaRoutingUiMiddleware:
    """Inject routing UI and guard over-eager media-route classifications."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")

        if method == "POST" and path == MEDIA_ROUTE_PATH:
            await self._guard_route_request(scope, receive, send)
            return

        if method != "GET" or not _is_chat_html_path(path):
            await self.app(scope, receive, send)
            return

        await self._inject_ui(scope, receive, send)

    async def _guard_route_request(self, scope, receive, send):
        request_messages = []
        request_body_parts = []

        while True:
            message = await receive()
            request_messages.append(message)
            if message.get("type") != "http.request":
                break
            request_body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        request_body = b"".join(request_body_parts)
        replay_index = 0

        async def replay_receive():
            nonlocal replay_index
            if replay_index < len(request_messages):
                message = request_messages[replay_index]
                replay_index += 1
                return message
            return await receive()

        start_message = None
        body_parts = []

        async def capture(message):
            nonlocal start_message
            if message.get("type") == "http.response.start":
                start_message = dict(message)
                return
            if message.get("type") == "http.response.body":
                body_parts.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                return
            await send(message)

        started_at = time.perf_counter()
        await self.app(scope, replay_receive, capture)
        duration_ms = (time.perf_counter() - started_at) * 1000

        if start_message is None:
            return

        body = b"".join(body_parts)
        headers = list(start_message.get("headers") or [])
        content_type = next(
            (
                value.decode("latin-1").lower()
                for key, value in headers
                if key.lower() == b"content-type"
            ),
            "",
        )

        if (
            int(start_message.get("status") or 200) == 200
            and "application/json" in content_type
        ):
            guarded_body = guard_media_route_payload(
                request_body,
                body,
                duration_ms=duration_ms,
                record=True,
            )
            if guarded_body != body:
                body = guarded_body
                headers = [
                    (key, value)
                    for key, value in headers
                    if key.lower() not in {b"content-length", b"etag"}
                ]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                start_message["headers"] = headers

        await send(start_message)
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def _inject_ui(self, scope, receive, send):
        child_scope = dict(scope)
        extensions = dict(scope.get("extensions") or {})
        extensions.pop("http.response.pathsend", None)
        child_scope["extensions"] = extensions

        start_message = None
        body_parts = []
        passthrough = False

        async def capture(message):
            nonlocal start_message, passthrough
            message_type = message.get("type")

            if passthrough:
                await send(message)
                return

            if message_type == "http.response.start":
                start_message = dict(message)
                return

            if message_type == "http.response.body":
                body_parts.append(message.get("body", b""))
                return

            passthrough = True
            if start_message is not None:
                await send(start_message)
                start_message = None
            for part in body_parts:
                await send(
                    {
                        "type": "http.response.body",
                        "body": part,
                        "more_body": True,
                    }
                )
            body_parts.clear()
            await send(message)

        await self.app(child_scope, receive, capture)

        if passthrough or start_message is None:
            return

        body = b"".join(body_parts)
        headers = list(start_message.get("headers") or [])
        content_type = next(
            (
                value.decode("latin-1").lower()
                for key, value in headers
                if key.lower() == b"content-type"
            ),
            "",
        )

        if (
            int(start_message.get("status") or 200) == 200
            and content_type.startswith("text/html")
        ):
            body = inject_media_routing_script(body)
            headers = [
                (key, value)
                for key, value in headers
                if key.lower() not in {b"content-length", b"etag"}
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            start_message["headers"] = headers

        await send(start_message)
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )
