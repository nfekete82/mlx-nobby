"""Media-routing UI helpers, conservative route guard and local observatory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException


MEDIA_ROUTING_SCRIPT = (
    b'<script src="/assets/chat/media-routing-fallback.js?v=20260929-chat-fallback-v1"></script>'
)
ROUTING_OBSERVATORY_ASSETS = (
    b'<link rel="stylesheet" href="/assets/chat/routing-observatory.css?v=20260930-routing-v1">\n'
    + MEDIA_ROUTING_SCRIPT
    + b'\n<script src="/assets/chat/routing-observatory.js?v=20260930-routing-v1"></script>'
)
MEDIA_ROUTE_PATH = "/api/mlx/chat/actions/route"
LONG_PROMPT_CHARS = 600
CHAT_LIKE_PROMPT_CHARS = 320
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

_EXPLICIT_IMAGE_REQUEST = re.compile(
    r"(?:\b(?:erstelle|erstell|erzeugen|erzeuge|generiere|generieren|zeichne|zeichnen|male|malen|"
    r"mache|mach|render(?:e|n)?|create|generate|draw|paint|make|render)\b"
    r"[\s\S]{0,140}?\b(?:bild|foto|illustration|grafik|image|photo|picture|graphic)\b)"
    r"|(?:\b(?:bild|foto|illustration|grafik|image|photo|picture|graphic)\b"
    r"[\s\S]{0,140}?\b(?:erstellen|erzeuge|erzeugen|generiere|generieren|zeichnen|malen|"
    r"machen|rendern|create|generate|draw|paint|make|render)\b)",
    re.IGNORECASE,
)

_SHORTS_MEDIA_NOUN = (
    r"(?:youtube\s+shorts?|shorts|short[- ]videos?|kurzvideos?|"
    r"tiktok(?:[- ]videos?)?|reels?|(?:ein(?:en)?|a)\s+short)"
)
_SHORTS_CREATE_VERB = (
    r"(?:erstelle|erstell|erstellen|mach|mache|machen|generiere|generieren|"
    r"erzeuge|erzeugen|produziere|produzieren|baue|bauen|schneide|schneiden|"
    r"create|generate|produce|build)"
)
_EXPLICIT_SHORTS_REQUEST = re.compile(
    rf"(?:\b{_SHORTS_CREATE_VERB}\b[\s\S]{{0,160}}?\b{_SHORTS_MEDIA_NOUN}\b)"
    rf"|(?:\b{_SHORTS_MEDIA_NOUN}\b[\s\S]{{0,160}}?\b{_SHORTS_CREATE_VERB}\b)"
    r"|(?:\b(?:turn|convert)\b[\s\S]{0,160}?\b(?:into|to)\b"
    r"[\s\S]{0,60}?\b(?:youtube\s+short|short[- ]video|tiktok(?:[- ]video)?|reel)\b)",
    re.IGNORECASE,
)

_EXPLICIT_VIDEO_REQUEST = re.compile(
    r"(?:\b(?:erstelle|erstell|erzeugen|erzeuge|generiere|generieren|mache|mach|"
    r"produziere|produzieren|animiere|animieren|create|generate|make|produce|animate)\b"
    r"[\s\S]{0,140}?\b(?:video|clip|animation|film|movie)\b)"
    r"|(?:\b(?:video|clip|animation|film|movie)\b[\s\S]{0,140}?"
    r"\b(?:erstellen|erzeugen|generieren|machen|produzieren|animieren|create|generate|"
    r"make|produce|animate)\b)",
    re.IGNORECASE,
)

_VISUAL_PROMPT_HINT = re.compile(
    r"\b(?:photorealistic|fotorealistisch|cinematic|cinematisch|portrait|porträt|portraitaufnahme|"
    r"composition|komposition|lighting|beleuchtung|lens|objektiv|bokeh|depth of field|tiefenschärfe|"
    r"aspect ratio|seitenverhältnis|negative prompt|watercolor|aquarell|concept art|konzeptkunst|"
    r"studio lighting|volumetric|ultra detailed|highly detailed|8k|4k|close[ -]?up|nahaufnahme|"
    r"full[ -]?body|ganzkörper|camera shot|kameraperspektive)\b",
    re.IGNORECASE,
)

_CHAT_LIKE_LEAD = re.compile(
    r"^\s*(?:erklär(?:e|en)?|analysier(?:e|en)?|prüf(?:e|en)?|pruef(?:e|en)?|fass(?:e|en)?|"
    r"zusammenfass(?:e|en)?|schau(?:e)?|bewert(?:e|en)?|vergleich(?:e|en)?|hilf(?:e)?|"
    r"was|wie|warum|wann|wo|wer|welche|welcher|welches|ist|sind|hat|haben|"
    r"kannst\s+du|könntest\s+du|koenntest\s+du|ich\s+habe|hier\s+ist|folgender|folgende|"
    r"explain|analy[sz]e|check|review|summari[sz]e|compare|help|what|how|why|when|where|who|"
    r"can\s+you|could\s+you|i\s+have|here\s+is|the\s+following)\b",
    re.IGNORECASE,
)


def _is_chat_html_path(path: str) -> bool:
    return path in {"/", "/chat", "/settings"} or path.startswith("/settings/")


def inject_media_routing_script(body: bytes) -> bytes:
    if ROUTING_OBSERVATORY_ASSETS in body:
        return body

    marker = b"</body>"
    if marker in body:
        return body.replace(marker, ROUTING_OBSERVATORY_ASSETS + b"\n" + marker, 1)

    return body


def _visual_prompt_hint_count(prompt: str) -> int:
    return len({match.group(0).casefold() for match in _VISUAL_PROMPT_HINT.finditer(prompt)})


def _has_explicit_shorts_request(prompt: str) -> bool:
    """Require an actual Shorts creation instruction, especially for pasted prose."""
    text = str(prompt or "").strip()
    if not text:
        return False

    if len(text) <= LONG_PROMPT_CHARS:
        search_text = text
    else:
        # A real request around pasted source material normally sits at the start
        # or the end. Ignoring the middle prevents quoted prose from triggering a job.
        search_text = text[:400] + "\n" + text[-400:]

    return bool(_EXPLICIT_SHORTS_REQUEST.search(search_text))


def _explicit_intent(prompt: str, target: str, action: str | None = None) -> bool:
    text = str(prompt or "").strip()
    action = str(action or "").strip()

    if action:
        if target == "image" and action.startswith("image_"):
            return True
        if target in {"video", "video_generate", "video_animate"} and action.startswith("video_"):
            return True

    if target == "image":
        return bool(_EXPLICIT_IMAGE_REQUEST.search(text))
    if target == "shorts_generate":
        return _has_explicit_shorts_request(text)
    if target in {"video", "video_generate", "video_animate"}:
        return bool(_EXPLICIT_VIDEO_REQUEST.search(text))
    return False


def _dedicated_media_prompt(prompt: str, target: str) -> bool:
    return target == "image" and _visual_prompt_hint_count(str(prompt or "")) >= 3


def _coerce_confidence(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 1:
        return None
    return round(confidence, 4)


def _derived_confidence(prompt: str, target: str, action: str | None = None) -> float | None:
    if _explicit_intent(prompt, target, action):
        return 1.0 if action else 0.98

    if target == "image":
        if _dedicated_media_prompt(prompt, target):
            return 0.86
        return 0.62

    if target == "shorts_generate":
        return 0.45

    if target in {"video", "video_generate", "video_animate"}:
        return 0.60

    return None


def route_confidence(
    prompt: str,
    target: str,
    response_payload: dict,
    action: str | None = None,
) -> tuple[float | None, str]:
    router_confidence = _coerce_confidence(response_payload.get("confidence"))
    if router_confidence is not None:
        return router_confidence, "router"

    derived = _derived_confidence(prompt, target, action)
    if derived is not None:
        return derived, "heuristic"

    return None, "unavailable"


def conservative_media_target(prompt: str, target: str) -> str:
    """Demote weak media classifications back to normal chat.

    Image generation remains available for explicit requests and dedicated
    visual prompts. Shorts generation is stricter because it starts a costly,
    multi-step media workflow: mentions of Shorts, TikTok or Reels alone are
    never enough; an explicit creation instruction is required.
    """
    text = str(prompt or "").strip()

    if target == "shorts_generate":
        return target if _has_explicit_shorts_request(text) else "chat"

    if target != "image":
        return target

    if not text:
        return target

    if _EXPLICIT_IMAGE_REQUEST.search(text):
        return target

    if _visual_prompt_hint_count(text) >= 3:
        return target

    if len(text) >= LONG_PROMPT_CHARS:
        return "chat"

    if len(text) >= CHAT_LIKE_PROMPT_CHARS and _CHAT_LIKE_LEAD.search(text):
        return "chat"

    return target


def confidence_guard_target(
    prompt: str,
    target: str,
    confidence: float | None,
    action: str | None = None,
) -> tuple[str, str | None]:
    """Apply the conservative confidence policy to active media actions."""
    if target not in ACTIVE_MEDIA_TARGETS or confidence is None:
        return target, None

    if confidence >= 0.90:
        return target, "high_confidence"

    if confidence < 0.65:
        return "chat", "low_confidence_fallback"

    if _explicit_intent(prompt, target, action) or _dedicated_media_prompt(prompt, target):
        return target, "medium_confidence_explicit_intent"

    return "chat", "medium_confidence_requires_explicit_intent"


def _normalized_prompt_preview(prompt: str, limit: int = 220) -> str:
    normalized = " ".join(str(prompt or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _intent_name(prompt: str, target: str, action: str | None = None) -> str:
    if _explicit_intent(prompt, target, action):
        if target == "image":
            return "explicit_image"
        if target == "shorts_generate":
            return "explicit_short"
        if target in {"video", "video_generate", "video_animate"}:
            return "explicit_video"
    if _dedicated_media_prompt(prompt, target):
        return "visual_prompt"
    if target == "chat":
        return "normal_chat"
    return "router_classification"


def _guard_reason(
    prompt: str,
    original_target: str,
    conservative_target: str,
) -> str | None:
    if conservative_target == original_target:
        return None
    if original_target == "shorts_generate":
        return "explicit_shorts_intent_required"
    if original_target == "image":
        return "long_form_chat_fallback"
    return "conservative_fallback"


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

    return {
        "version": 1,
        "decisions": [item for item in decisions if isinstance(item, dict)][-ROUTING_DECISION_LIMIT:],
    }


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
    conservative_target = conservative_media_target(prompt, original_target)
    reason = _guard_reason(prompt, original_target, conservative_target)

    confidence, confidence_source = route_confidence(
        prompt,
        original_target,
        response_payload,
        action,
    )

    guarded_target = conservative_target
    confidence_reason = None
    if guarded_target == original_target:
        guarded_target, confidence_reason = confidence_guard_target(
            prompt,
            original_target,
            confidence,
            action,
        )
        if guarded_target != original_target:
            reason = confidence_reason

    if guarded_target != original_target:
        response_payload["target"] = guarded_target
        response_payload["routing_guard"] = reason or "confidence_fallback"

    decision_id = uuid.uuid4().hex
    trace = {
        "id": decision_id,
        "created_at": time.time(),
        "prompt_preview": _normalized_prompt_preview(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_chars": len(prompt),
        "intent": _intent_name(prompt, original_target, action),
        "original_target": original_target,
        "target": guarded_target,
        "confidence": confidence,
        "confidence_source": confidence_source,
        "reason": reason or confidence_reason or "router_decision",
        "guarded": guarded_target != original_target,
        "fallback": guarded_target if guarded_target != original_target else None,
        "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
    }

    response_payload["routing_observatory"] = {
        "id": decision_id,
        "original_target": original_target,
        "target": guarded_target,
        "confidence": confidence,
        "confidence_source": confidence_source,
        "reason": trace["reason"],
        "guarded": trace["guarded"],
    }

    if record:
        record_routing_decision(trace)

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
