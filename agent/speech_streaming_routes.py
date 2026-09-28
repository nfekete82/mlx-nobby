"""Transparent speech proxy from the agent to the local speech service."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


SPEECH_SERVICE_URL = os.environ.get(
    "SPEECH_SERVICE_URL",
    "http://127.0.0.1:8050",
).rstrip("/")


def _http_error_detail(exc):
    body = exc.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body).get("detail", body)
    except Exception:
        return body


def _upstream_stream(payload: dict):
    request = urllib.request.Request(
        f"{SPEECH_SERVICE_URL}/v1/audio/speech/stream",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
        },
        method="POST",
    )

    try:
        return urllib.request.urlopen(request, timeout=900)
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=exc.code,
            detail=_http_error_detail(exc),
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Speech-Dienst nicht erreichbar") from exc


def _upstream_json(path: str):
    request = urllib.request.Request(
        f"{SPEECH_SERVICE_URL}{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=exc.code,
            detail=_http_error_detail(exc),
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Speech-Dienst nicht erreichbar") from exc


def install_routes(app):
    route_paths = {getattr(route, "path", None) for route in app.routes}

    if "/api/mlx/audio/voices" not in route_paths:
        @app.get("/api/mlx/audio/voices")
        def speech_voices():
            return _upstream_json("/v1/audio/voices")

    if "/api/mlx/audio/speech/stream" in route_paths:
        return

    @app.post("/api/mlx/audio/speech/stream")
    def speech_stream(payload: dict):
        upstream = _upstream_stream(payload)

        def chunks():
            try:
                while True:
                    data = upstream.read(16 * 1024)
                    if not data:
                        break
                    yield data
            finally:
                upstream.close()

        return StreamingResponse(
            chunks(),
            status_code=getattr(upstream, "status", 200),
            media_type=upstream.headers.get(
                "Content-Type",
                "application/x-ndjson",
            ),
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
