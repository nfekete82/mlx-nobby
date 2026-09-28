"""Voice manager proxy from the local agent to the speech service."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request, Response


SPEECH_SERVICE_URL = os.environ.get(
    "SPEECH_SERVICE_URL",
    "http://127.0.0.1:8050",
).rstrip("/")


def _detail(exc):
    body = exc.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body).get("detail", body)
    except Exception:
        return body


async def _proxy(request: Request, path: str, *, timeout: int = 30):
    body = await request.body()
    headers = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    upstream_request = urllib.request.Request(
        f"{SPEECH_SERVICE_URL}{path}",
        data=body if body else None,
        headers=headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(upstream_request, timeout=timeout) as upstream:
            payload = upstream.read()
            response_headers = {"Cache-Control": "no-store"}
            disposition = upstream.headers.get("Content-Disposition")
            if disposition:
                response_headers["Content-Disposition"] = disposition
            return Response(
                content=payload,
                status_code=getattr(upstream, "status", 200),
                media_type=upstream.headers.get("Content-Type", "application/json"),
                headers=response_headers,
            )
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, _detail(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Speech-Dienst nicht erreichbar") from exc


def _voice_path(voice: str, suffix: str = ""):
    encoded = urllib.parse.quote(str(voice), safe="")
    return f"/v1/audio/voices/{encoded}{suffix}"


def install_routes(app):
    methods_by_path = {
        (getattr(route, "path", None), method)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }

    if ("/api/mlx/audio/voices/manage", "GET") not in methods_by_path:
        @app.get("/api/mlx/audio/voices/manage")
        async def list_voices(request: Request):
            return await _proxy(request, "/v1/audio/voices/manage")

    if ("/api/mlx/audio/voice-default", "PUT") not in methods_by_path:
        @app.put("/api/mlx/audio/voice-default")
        async def set_default(request: Request):
            return await _proxy(request, "/v1/audio/voice-default")

    if ("/api/mlx/audio/voices/import", "POST") not in methods_by_path:
        @app.post("/api/mlx/audio/voices/import")
        async def import_voice(request: Request):
            return await _proxy(request, "/v1/audio/voices/import", timeout=180)

    if ("/api/mlx/audio/voices/{voice}/reference", "GET") not in methods_by_path:
        @app.get("/api/mlx/audio/voices/{voice}/reference")
        async def reference(voice: str, request: Request):
            return await _proxy(request, _voice_path(voice, "/reference"))

    if ("/api/mlx/audio/voices/{voice}", "GET") not in methods_by_path:
        @app.get("/api/mlx/audio/voices/{voice}")
        async def details(voice: str, request: Request):
            return await _proxy(request, _voice_path(voice))

    if ("/api/mlx/audio/voices/{voice}", "PUT") not in methods_by_path:
        @app.put("/api/mlx/audio/voices/{voice}")
        async def update_voice(voice: str, request: Request):
            return await _proxy(request, _voice_path(voice))

    if ("/api/mlx/audio/voices/{voice}", "DELETE") not in methods_by_path:
        @app.delete("/api/mlx/audio/voices/{voice}")
        async def delete_voice(voice: str, request: Request):
            return await _proxy(request, _voice_path(voice))
