"""Web proxy routes and HTML hook for Model Scout."""

from __future__ import annotations

import urllib.parse

from fastapi import FastAPI, Query


MODEL_SCOUT_SCRIPT = (
    b'<script src="/assets/chat/model-scout-loader.js?v=20260929-model-scout-loader-v4"></script>'
)
CHAT_SCRIPT_MARKER = b'<script src="/assets/chat.js?v=20260926-shorts-progress"></script>'


def _is_chat_html_path(path: str) -> bool:
    return path in {"/", "/chat", "/settings"} or path.startswith("/settings/")


def inject_model_scout_script(body: bytes) -> bytes:
    if MODEL_SCOUT_SCRIPT in body:
        return body
    if CHAT_SCRIPT_MARKER in body:
        return body.replace(
            CHAT_SCRIPT_MARKER,
            MODEL_SCOUT_SCRIPT + b"\n" + CHAT_SCRIPT_MARKER,
            1,
        )
    marker = b"</body>"
    if marker in body:
        return body.replace(marker, MODEL_SCOUT_SCRIPT + b"\n" + marker, 1)
    return body


class ModelScoutUiMiddleware:
    """Inject the Model Scout module into chat/settings HTML only."""

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
            body = inject_model_scout_script(body)
            headers = [
                (key, value)
                for key, value in headers
                if key.lower() not in {b"content-length", b"etag"}
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            start_message["headers"] = headers

        await send(start_message)
        await send({"type": "http.response.body", "body": body, "more_body": False})


def install_routes(app: FastAPI, agent_json_request) -> None:
    paths = {getattr(route, "path", None) for route in app.router.routes}

    if "/api/mlx/model-scout/profile" not in paths:
        @app.get("/api/mlx/model-scout/profile")
        def model_scout_profile():
            return agent_json_request("GET", "/api/model-scout/profile", timeout=10)

    if "/api/mlx/model-scout/discover" not in paths:
        @app.get("/api/mlx/model-scout/discover")
        def model_scout_discover(
            limit: int = Query(default=30, ge=1, le=100),
            role: str = Query(default="all", pattern="^(all|chat|coding|vision)$"),
        ):
            return agent_json_request(
                "GET",
                "/api/model-scout/discover?limit=" + str(limit) + "&role=" + role,
                timeout=25,
            )

    if "/api/mlx/model-scout/benchmarks" not in paths:
        @app.post("/api/mlx/model-scout/benchmarks", status_code=202)
        def model_scout_start_benchmark(request: dict):
            return agent_json_request(
                "POST",
                "/api/model-scout/benchmarks",
                payload=request,
                timeout=15,
            )

        @app.get("/api/mlx/model-scout/benchmarks")
        def model_scout_benchmark_history():
            return agent_json_request(
                "GET",
                "/api/model-scout/benchmarks",
                timeout=15,
            )

    if "/api/mlx/model-scout/benchmarks/{job_id}" not in paths:
        @app.get("/api/mlx/model-scout/benchmarks/{job_id}")
        def model_scout_benchmark_job(job_id: str):
            return agent_json_request(
                "GET",
                "/api/model-scout/benchmarks/" + urllib.parse.quote(job_id, safe=""),
                timeout=15,
            )


__all__ = [
    "MODEL_SCOUT_SCRIPT",
    "ModelScoutUiMiddleware",
    "inject_model_scout_script",
    "install_routes",
]
