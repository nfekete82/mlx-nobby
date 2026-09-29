"""Inject the media-routing fallback helper into the chat UI."""

from __future__ import annotations


MEDIA_ROUTING_SCRIPT = (
    b'<script src="/assets/chat/media-routing-fallback.js?v=20260929-chat-fallback-v1"></script>'
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


class MediaRoutingUiMiddleware:
    """Add the chat fallback behavior to chat/settings HTML responses."""

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
