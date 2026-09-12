"""Fixed native service routes for Docker. No arbitrary URL/path forwarding."""
import json
import os
import time
import urllib.error
import urllib.request

from backend import observability
from fastapi import HTTPException, Request
from fastapi.responses import Response


def forward(
    url,
    data=None,
    content_type="application/json",
    timeout=900,
    call_metrics=None,
    expose_metrics=False,
):
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": content_type},
        method="POST" if data is not None else "GET",
    )
    try:
        connect_started = time.monotonic()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if call_metrics:
                call_metrics.set_upstream_connect(
                    (time.monotonic() - connect_started) * 1000
                )
            body = response.read()
            if call_metrics:
                try:
                    result = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    result = {}
                choices = result.get("choices") if isinstance(result, dict) else []
                choice = choices[0] if isinstance(choices, list) and choices else {}
                message = choice.get("message", {})
                call_metrics.finish(
                    usage=result.get("usage"),
                    output_text=(
                        message.get("content")
                        or message.get("reasoning")
                        or ""
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
                if expose_metrics and isinstance(result, dict):
                    result["_mlx_metrics"] = observability.trace_snapshot(
                        call_metrics.trace_id
                    )
                    body = json.dumps(
                        result,
                        ensure_ascii=False,
                    ).encode("utf-8")
            return Response(body, status_code=response.status,
                            media_type=response.headers.get_content_type())
    except urllib.error.HTTPError as exc:
        if call_metrics:
            call_metrics.fail("http_error")
        return Response(exc.read(), status_code=exc.code,
                        media_type=exc.headers.get_content_type())
    except (urllib.error.URLError, TimeoutError) as exc:
        if call_metrics:
            call_metrics.fail(type(exc).__name__)
        raise HTTPException(503, "Nativer Dienst ist nicht erreichbar") from exc
    except Exception as exc:
        if call_metrics:
            call_metrics.fail(type(exc).__name__)
        raise


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
        trace_data = payload.pop("_mlx_observability", {})
        trace_data = trace_data if isinstance(trace_data, dict) else {}
        expose_metrics = bool(trace_data)
        call_metrics = observability.ModelCallMetrics(
            trace_id=trace_data.get("trace_id"),
            parent_request_id=trace_data.get("parent_request_id"),
            purpose=trace_data.get("purpose") or "chat.nonstream",
            model=payload.get("model"),
            role=trace_data.get("role"),
            backend=trace_data.get("backend"),
            messages=payload.get("messages"),
            context_sources=trace_data.get("context_sources"),
        )
        wait_started = time.monotonic()
        with runtime_lock:
            call_metrics.set_queue_wait(
                (time.monotonic() - wait_started) * 1000
            )
            return forward(f"http://127.0.0.1:{runtime_port()}/v1/chat/completions",
                           json.dumps(payload).encode("utf-8"),
                           call_metrics=call_metrics,
                           expose_metrics=expose_metrics)

    @app.post("/api/bridge/speech/v1/audio/transcriptions")
    async def speech(request: Request):
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data;"):
            raise HTTPException(415, "Multipart-Audiodatei erwartet")
        data = await request.body()  # LocalRequestGuard bounds the raw stream.
        url = os.environ.get("SPEECH_SERVICE_URL", "http://127.0.0.1:8050").rstrip("/")
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(forward, url + "/v1/audio/transcriptions", data, content_type, 180)
