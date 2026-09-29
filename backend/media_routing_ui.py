"""Media-routing UI helpers and conservative route guard."""

from __future__ import annotations

import json
import re


MEDIA_ROUTING_SCRIPT = (
    b'<script src="/assets/chat/media-routing-fallback.js?v=20260929-chat-fallback-v1"></script>'
)
MEDIA_ROUTE_PATH = "/api/mlx/chat/actions/route"
LONG_PROMPT_CHARS = 600
CHAT_LIKE_PROMPT_CHARS = 320

_EXPLICIT_IMAGE_REQUEST = re.compile(
    r"(?:\b(?:erstelle|erstell|erzeugen|erzeuge|generiere|generieren|zeichne|zeichnen|male|malen|"
    r"mache|mach|render(?:e|n)?|create|generate|draw|paint|make|render)\b"
    r"[\s\S]{0,140}?\b(?:bild|foto|illustration|grafik|image|photo|picture|graphic)\b)"
    r"|(?:\b(?:bild|foto|illustration|grafik|image|photo|picture|graphic)\b"
    r"[\s\S]{0,140}?\b(?:erstellen|erzeuge|erzeugen|generiere|generieren|zeichnen|malen|"
    r"machen|rendern|create|generate|draw|paint|make|render)\b)",
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
    if MEDIA_ROUTING_SCRIPT in body:
        return body

    marker = b"</body>"
    if marker in body:
        return body.replace(marker, MEDIA_ROUTING_SCRIPT + b"\n" + marker, 1)

    return body


def _visual_prompt_hint_count(prompt: str) -> int:
    return len({match.group(0).casefold() for match in _VISUAL_PROMPT_HINT.finditer(prompt)})


def conservative_media_target(prompt: str, target: str) -> str:
    """Demote weak long-form image classifications back to normal chat.

    Short prompts keep the semantic router's decision. Longer prose must either
    contain an explicit image-creation instruction or look strongly like a
    dedicated visual prompt. This prevents ordinary pasted text from opening
    the image-quality dialog just because it happens to mention images.
    """
    if target != "image":
        return target

    text = str(prompt or "").strip()
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


def guard_media_route_payload(request_body: bytes, response_body: bytes) -> bytes:
    """Rewrite a weak image route response to chat, leaving all else untouched."""
    try:
        request_payload = json.loads(request_body.decode("utf-8"))
        response_payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return response_body

    if not isinstance(request_payload, dict) or not isinstance(response_payload, dict):
        return response_body

    original_target = str(response_payload.get("target") or "")
    guarded_target = conservative_media_target(
        str(request_payload.get("prompt") or ""),
        original_target,
    )

    if guarded_target == original_target:
        return response_body

    response_payload["target"] = guarded_target
    response_payload["routing_guard"] = "long_form_chat_fallback"
    return json.dumps(
        response_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class MediaRoutingUiMiddleware:
    """Inject UI fallback and guard over-eager image-route classifications."""

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

        await self.app(scope, replay_receive, capture)

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
            guarded_body = guard_media_route_payload(request_body, body)
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
