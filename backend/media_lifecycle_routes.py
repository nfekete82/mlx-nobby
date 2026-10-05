"""Web proxy routes and browser hook for generated-media cleanup."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException


MEDIA_LIFECYCLE_SCRIPT = (
    b'<script src="/assets/chat/media-lifecycle.js?v=20261005-media-lifecycle-v1"></script>'
)


def inject_media_lifecycle_script(body: bytes) -> bytes:
    if MEDIA_LIFECYCLE_SCRIPT in body:
        return body
    marker = b"</body>"
    if marker not in body:
        return body
    return body.replace(marker, MEDIA_LIFECYCLE_SCRIPT + b"\n" + marker, 1)


class MediaLifecycleUiMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = str(scope.get("path") or "")
        if (
            scope.get("type") != "http"
            or scope.get("method") != "GET"
            or not (
                path in {"/", "/chat", "/chat.html", "/settings"}
                or path.startswith("/settings/")
            )
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
            if passthrough:
                await send(message)
                return
            kind = message.get("type")
            if kind == "http.response.start":
                start_message = dict(message)
                return
            if kind == "http.response.body":
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
            patched = inject_media_lifecycle_script(body)
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


def install_routes(app: FastAPI, agent_json_request) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    def proxy(method, path, *, payload=None, timeout=20):
        try:
            return agent_json_request(method, path, payload=payload, timeout=timeout)
        except HTTPException as exc:
            if exc.status_code in {404, 409, 422, 503}:
                raise
            raise HTTPException(exc.status_code, "Media-Lifecycle-Anfrage fehlgeschlagen") from exc

    if "/api/mlx/media-lifecycle/status" not in paths:
        @app.get("/api/mlx/media-lifecycle/status")
        def media_lifecycle_status():
            return proxy("GET", "/api/media-lifecycle/status")

    if "/api/mlx/media-lifecycle/persist" not in paths:
        @app.post("/api/mlx/media-lifecycle/persist")
        def media_lifecycle_persist(payload: dict):
            return proxy("POST", "/api/media-lifecycle/persist", payload=payload)

    if "/api/mlx/media-lifecycle/discard" not in paths:
        @app.post("/api/mlx/media-lifecycle/discard")
        def media_lifecycle_discard(payload: dict):
            return proxy("POST", "/api/media-lifecycle/discard", payload=payload)

    if "/api/mlx/media-lifecycle/cleanup" not in paths:
        @app.post("/api/mlx/media-lifecycle/cleanup")
        def media_lifecycle_cleanup():
            return proxy("POST", "/api/media-lifecycle/cleanup", payload={})


__all__ = [
    "MEDIA_LIFECYCLE_SCRIPT",
    "MediaLifecycleUiMiddleware",
    "inject_media_lifecycle_script",
    "install_routes",
]
