"""Web proxy routes and HTML hook for System Health & Self-Healing v1."""

from __future__ import annotations

import urllib.parse

from fastapi import FastAPI


SYSTEM_HEALTH_SCRIPT = (
    b'<script src="/assets/chat/system-health.js?v=20260929-system-health-v1"></script>'
)
CHAT_SCRIPT_MARKER = b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'


def _is_chat_html_path(path: str) -> bool:
    return (
        path in {"/", "/chat", "/settings"}
        or path.startswith("/settings/")
    )


def inject_system_health_script(body: bytes) -> bytes:
    if SYSTEM_HEALTH_SCRIPT in body:
        return body
    if CHAT_SCRIPT_MARKER in body:
        return body.replace(
            CHAT_SCRIPT_MARKER,
            SYSTEM_HEALTH_SCRIPT + b"\n" + CHAT_SCRIPT_MARKER,
            1,
        )
    marker = b"</body>"
    if marker in body:
        return body.replace(
            marker,
            SYSTEM_HEALTH_SCRIPT + b"\n" + marker,
            1,
        )
    return body


class SystemHealthUiMiddleware:
    """Inject the health dashboard module into chat/settings HTML only."""

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
            body = inject_system_health_script(body)
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

    if "/api/mlx/system/health-v1" not in paths:
        @app.get("/api/mlx/system/health-v1")
        def system_health_v1():
            return agent_json_request(
                "GET",
                "/api/system/health-v1",
                timeout=20,
            )

    if "/api/mlx/system/services/{service_id}/restart" not in paths:
        @app.post("/api/mlx/system/services/{service_id}/restart")
        def system_service_restart(service_id: str):
            return agent_json_request(
                "POST",
                "/api/system/services/" +
                urllib.parse.quote(service_id, safe="") +
                "/restart",
                payload={},
                timeout=70,
            )

    if "/api/mlx/system/self-heal" not in paths:
        @app.post("/api/mlx/system/self-heal")
        def system_self_heal():
            return agent_json_request(
                "POST",
                "/api/system/self-heal",
                payload={},
                timeout=120,
            )


__all__ = [
    "SYSTEM_HEALTH_SCRIPT",
    "SystemHealthUiMiddleware",
    "inject_system_health_script",
    "install_routes",
]
