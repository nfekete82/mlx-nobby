"""Web proxy routes and HTML hook for the Nobby Memory manager."""

from __future__ import annotations

import urllib.parse

from fastapi import FastAPI


MEMORY_MANAGER_SCRIPT = (
    b'<script src="/assets/chat/memory-manager.js?v=20260928-memory-manager-v1"></script>'
)
CHAT_SCRIPT_MARKER = b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'


def _is_chat_html_path(path: str) -> bool:
    return (
        path in {"/", "/chat", "/settings"}
        or path.startswith("/settings/")
    )


def inject_memory_manager_script(body: bytes) -> bytes:
    """Inject the manager before chat.js without modifying the large HTML file."""
    if MEMORY_MANAGER_SCRIPT in body:
        return body

    if CHAT_SCRIPT_MARKER in body:
        return body.replace(
            CHAT_SCRIPT_MARKER,
            MEMORY_MANAGER_SCRIPT + b"\n" + CHAT_SCRIPT_MARKER,
            1,
        )

    marker = b"</body>"
    if marker in body:
        return body.replace(
            marker,
            MEMORY_MANAGER_SCRIPT + b"\n" + marker,
            1,
        )

    return body


class MemoryManagerUiMiddleware:
    """Inject the memory UI script into chat/settings HTML responses only."""

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

        # Force normal body messages so FileResponse can be safely rewritten.
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

            # Unknown response extensions are safer to forward unchanged.
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

        if passthrough:
            return

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
            and content_type.startswith("text/html")
        ):
            body = inject_memory_manager_script(body)
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
    paths = {
        getattr(route, "path", None)
        for route in app.router.routes
    }

    if "/api/mlx/memory" not in paths:
        @app.get("/api/mlx/memory")
        def memory_list(include_disabled: bool = True, limit: int = 500):
            query = urllib.parse.urlencode({
                "include_disabled": "true" if include_disabled else "false",
                "limit": max(1, min(int(limit), 1000)),
            })
            return agent_json_request(
                "GET",
                "/api/memory?" + query,
                timeout=10,
            )

        @app.post("/api/mlx/memory")
        def memory_create(payload: dict):
            return agent_json_request(
                "POST",
                "/api/memory",
                payload=payload,
                timeout=10,
            )

    if "/api/mlx/memory/{memory_id}" not in paths:
        @app.patch("/api/mlx/memory/{memory_id}")
        def memory_update(memory_id: str, payload: dict):
            return agent_json_request(
                "PATCH",
                "/api/memory/" + urllib.parse.quote(memory_id, safe=""),
                payload=payload,
                timeout=10,
            )

        @app.delete("/api/mlx/memory/{memory_id}")
        def memory_delete(memory_id: str):
            return agent_json_request(
                "DELETE",
                "/api/memory/" + urllib.parse.quote(memory_id, safe=""),
                timeout=10,
            )

    if "/api/mlx/memory/context" not in paths:
        @app.get("/api/mlx/memory/context")
        def memory_context(query: str, limit: int = 6):
            params = urllib.parse.urlencode({
                "query": query,
                "limit": max(1, min(int(limit), 12)),
            })
            return agent_json_request(
                "GET",
                "/api/memory/context?" + params,
                timeout=10,
            )


__all__ = [
    "MemoryManagerUiMiddleware",
    "inject_memory_manager_script",
    "install_routes",
]
