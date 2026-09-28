"""Transparent streaming proxy from the web backend to the local agent."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


def install_routes(app, agent_url: str):
    if any(
        getattr(route, "path", None) == "/api/mlx/audio/speech/stream"
        for route in app.routes
    ):
        return

    @app.post("/api/mlx/audio/speech/stream")
    def speech_stream(payload: dict):
        request = urllib.request.Request(
            f"{agent_url.rstrip('/')}/api/mlx/audio/speech/stream",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson",
            },
            method="POST",
        )

        try:
            upstream = urllib.request.urlopen(request, timeout=900)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body).get("detail", body)
            except Exception:
                detail = body
            raise HTTPException(status_code=exc.code, detail=detail) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise HTTPException(503, "Agent nicht erreichbar") from exc

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
