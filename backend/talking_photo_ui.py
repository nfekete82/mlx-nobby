"""Inject the Talking Photo browser modules without forking the large chat HTML."""

from __future__ import annotations


_SCRIPTS = (
    b'<script src="/assets/chat/talking-photo.js?v=20261004-talking-photo"></script>\n'
    b'<script src="/assets/chat/talking-photo-clipboard.js?v=20261004-talking-photo-clipboard"></script>\n'
)


def patch_chat_html(body: bytes) -> bytes:
    if _SCRIPTS.strip() in body:
        return body
    marker = b"</body>"
    if marker not in body:
        return body
    return body.replace(marker, _SCRIPTS + marker, 1)


class TalkingPhotoUiMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        serves_chat_html = (
            path in {"/", "/chat", "/chat.html", "/settings"}
            or path.startswith("/settings/")
        )
        if method != "GET" or not serves_chat_html:
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
                await send({
                    "type": "http.response.body",
                    "body": part,
                    "more_body": True,
                })
            body_parts.clear()
            await send(message)

        await self.app(child_scope, receive, capture)

        if passthrough or start_message is None:
            return

        body = b"".join(body_parts)
        if int(start_message.get("status") or 200) == 200:
            patched = patch_chat_html(body)
            if patched != body:
                body = patched
                headers = [
                    (key, value)
                    for key, value in list(start_message.get("headers") or [])
                    if key.lower() not in {b"content-length", b"etag"}
                ]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                start_message["headers"] = headers

        await send(start_message)
        await send({"type": "http.response.body", "body": body, "more_body": False})
