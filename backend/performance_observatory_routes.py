"""Web proxy and HTML asset hook for Performance Observatory v2."""

from __future__ import annotations

import urllib.parse

from fastapi import FastAPI


PERFORMANCE_OBSERVATORY_ASSETS = (
    b'<link id="mlx-performance-observatory-css" rel="stylesheet" href="/assets/chat/performance-observatory.css?v=20260930-performance-v2">\n'
    b'<script src="/assets/chat/performance-observatory.js?v=20260930-performance-v2"></script>'
)
CHAT_SCRIPT_MARKER = b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'


def _is_chat_html_path(path: str) -> bool:
    return path in {"/", "/chat", "/settings"} or path.startswith("/settings/")


def inject_performance_observatory_assets(body: bytes) -> bytes:
    if PERFORMANCE_OBSERVATORY_ASSETS in body:
        return body
    if CHAT_SCRIPT_MARKER in body:
        return body.replace(
            CHAT_SCRIPT_MARKER,
            PERFORMANCE_OBSERVATORY_ASSETS + b"\n" + CHAT_SCRIPT_MARKER,
            1,
        )
    marker = b"</body>"
    if marker in body:
        return body.replace(
            marker,
            PERFORMANCE_OBSERVATORY_ASSETS + b"\n" + marker,
            1,
        )
    return body


class PerformanceObservatoryUiMiddleware:
    """Inject Performance Observatory assets into chat/settings HTML only."""

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
            body = inject_performance_observatory_assets(body)
            headers = [
                (key, value)
                for key, value in headers
                if key.lower() not in {b"content-length", b"etag"}
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            start_message["headers"] = headers

        await send(start_message)
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })


def install_routes(app: FastAPI, agent_json_request) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}
    if "/api/mlx/performance/observatory" in paths:
        return

    @app.get("/api/mlx/performance/observatory")
    def performance_observatory(limit: int = 40):
        try:
            resolved_limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError):
            resolved_limit = 40
        return agent_json_request(
            "GET",
            "/api/performance/observatory?" + urllib.parse.urlencode({
                "limit": resolved_limit,
            }),
            timeout=20,
        )


__all__ = [
    "PERFORMANCE_OBSERVATORY_ASSETS",
    "PerformanceObservatoryUiMiddleware",
    "inject_performance_observatory_assets",
    "install_routes",
]
