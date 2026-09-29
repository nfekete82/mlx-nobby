"""HTML hook for the compact settings information architecture."""

from __future__ import annotations


SETTINGS_CSS = (
    b'<link rel="stylesheet" href="/assets/chat/settings-layout.css?v=20260929-settings-layout-v1">'
)
SETTINGS_SCRIPT = (
    b'<script src="/assets/chat/settings-layout.js?v=20260929-settings-layout-v1"></script>'
)


def _is_chat_html_path(path: str) -> bool:
    return path in {"/", "/chat", "/settings"} or path.startswith("/settings/")


def inject_settings_ui(body: bytes) -> bytes:
    result = body
    if SETTINGS_CSS not in result:
        head_marker = b"</head>"
        if head_marker in result:
            result = result.replace(head_marker, SETTINGS_CSS + b"\n" + head_marker, 1)
    if SETTINGS_SCRIPT not in result:
        body_marker = b"</body>"
        if body_marker in result:
            result = result.replace(body_marker, SETTINGS_SCRIPT + b"\n" + body_marker, 1)
    return result


class SettingsUiMiddleware:
    """Inject compact settings navigation into chat/settings HTML only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "GET"
            or not _is_chat_html_path(str(scope.get("path") or ""))
        ):
            await self.app(scope, receive, send)
            return

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
                await send({"type": "http.response.body", "body": part, "more_body": True})
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

        if int(start_message.get("status") or 200) == 200 and content_type.startswith("text/html"):
            body = inject_settings_ui(body)
            headers = [
                (key, value)
                for key, value in headers
                if key.lower() not in {b"content-length", b"etag"}
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            start_message["headers"] = headers

        await send(start_message)
        await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = [
    "SETTINGS_CSS",
    "SETTINGS_SCRIPT",
    "SettingsUiMiddleware",
    "inject_settings_ui",
]
