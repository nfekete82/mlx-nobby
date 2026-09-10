"""Fixed native service routes for Docker. No arbitrary URL/path forwarding."""
import json
import os
import urllib.error
import urllib.request

from fastapi import HTTPException, Request
from fastapi.responses import Response


def forward(url, data=None, content_type="application/json", timeout=900):
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": content_type},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.read(), status_code=response.status,
                            media_type=response.headers.get_content_type())
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status_code=exc.code,
                        media_type=exc.headers.get_content_type())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Nativer Dienst ist nicht erreichbar") from exc


def install_routes(app, runtime_port, runtime_lock):
    @app.get("/api/bridge/mlx/v1/models")
    def models():
        return forward(f"http://127.0.0.1:{runtime_port()}/v1/models", timeout=10)

    @app.post("/api/bridge/mlx/v1/chat/completions")
    def chat(payload: dict):
        # These existing callers return a single response; role-aware streaming
        # continues to use /api/runtime/chat/stream.
        if payload.get("stream"):
            raise HTTPException(422, "Streaming benötigt /api/runtime/chat/stream")
        with runtime_lock:
            return forward(f"http://127.0.0.1:{runtime_port()}/v1/chat/completions",
                           json.dumps(payload).encode("utf-8"))

    @app.post("/api/bridge/speech/v1/audio/transcriptions")
    async def speech(request: Request):
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data;"):
            raise HTTPException(415, "Multipart-Audiodatei erwartet")
        data = await request.body()  # LocalRequestGuard bounds the raw stream.
        url = os.environ.get("SPEECH_SERVICE_URL", "http://127.0.0.1:8050").rstrip("/")
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(forward, url + "/v1/audio/transcriptions", data, content_type, 180)
