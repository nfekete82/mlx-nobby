"""Resilient wrapper around the existing chat SSE gateway."""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from contextlib import suppress
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


FIRST_BYTE_TIMEOUT = max(
    10.0,
    float(os.environ.get("MLX_CHAT_FIRST_BYTE_TIMEOUT", "30")),
)
STREAM_STALL_TIMEOUT = max(
    15.0,
    float(os.environ.get("MLX_CHAT_STREAM_STALL_TIMEOUT", "45")),
)
MEDIA_WAIT_TIMEOUT = max(
    FIRST_BYTE_TIMEOUT,
    float(os.environ.get("MLX_CHAT_MEDIA_WAIT_TIMEOUT", "300")),
)
RECOVERY_READY_TIMEOUT = max(
    10.0,
    float(os.environ.get("MLX_CHAT_RECOVERY_READY_TIMEOUT", "30")),
)


class ReliableChatRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 3000
    system_prompt: str = ""
    trace_id: str | None = None
    context_sources: dict | None = None


def _json_request(method: str, url: str, payload=None, timeout=4):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _agent_diagnostics(agent_url: str) -> dict:
    try:
        return _json_request(
            "GET",
            agent_url.rstrip("/") + "/api/runtime/reliability",
            timeout=3,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "lease": {},
            "runtime": {},
            "recovery": {},
        }


def _request_recovery(agent_url: str, reason: str) -> dict:
    try:
        return _json_request(
            "POST",
            agent_url.rstrip("/") + "/api/runtime/reliability/recover",
            {"reason": reason, "force": False},
            timeout=5,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        return {
            "ok": False,
            "scheduled": False,
            "status_code": exc.code,
            "detail": detail,
        }
    except Exception as exc:
        return {
            "ok": False,
            "scheduled": False,
            "detail": str(exc),
        }


def _agent_ready_with_new_pid(agent_url: str, previous_pid, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    saw_unavailable = False

    while time.monotonic() < deadline:
        snapshot = _agent_diagnostics(agent_url)
        current_pid = snapshot.get("agent_pid")
        if snapshot.get("status") == "unavailable":
            saw_unavailable = True
        elif current_pid and (
            previous_pid is None
            or current_pid != previous_pid
            or saw_unavailable
        ):
            runtime = snapshot.get("runtime") or {}
            if runtime.get("online") is not False:
                return True
        time.sleep(0.35)

    return False


def _sse_error(message: str, code: str, *, retryable: bool) -> bytes:
    payload = json.dumps(
        {
            "error": message,
            "code": code,
            "retryable": retryable,
        },
        ensure_ascii=False,
    )
    return f"data: {payload}\n\n".encode("utf-8")


async def _close_iterator(iterator, pending_task=None):
    if pending_task is not None and not pending_task.done():
        pending_task.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
            await pending_task

    closer = getattr(iterator, "aclose", None)
    if closer is not None:
        with suppress(Exception):
            result = closer()
            if asyncio.iscoroutine(result):
                await result


async def _wait_for_next(iterator, timeout: float):
    task = asyncio.create_task(iterator.__anext__())
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if task in done:
        return True, task
    return False, task


def _media_is_active(snapshot: dict) -> bool:
    workload = (snapshot.get("lease") or {}).get("active_workload")
    return workload in {"image", "video"}


def _copy_headers(response) -> dict:
    ignored = {"content-length", "connection", "transfer-encoding"}
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in ignored
    }


async def _reliable_stream(
    request: ReliableChatRequest,
    *,
    stream_factory: Callable[[ReliableChatRequest], StreamingResponse],
    agent_url: str,
):
    emitted = False
    attempt = 0

    while attempt < 2:
        attempt += 1
        response = stream_factory(request)
        iterator = response.body_iterator.__aiter__()

        ready, pending = await _wait_for_next(iterator, FIRST_BYTE_TIMEOUT)

        if not ready:
            snapshot = await asyncio.to_thread(_agent_diagnostics, agent_url)

            if _media_is_active(snapshot):
                ready, pending = await _wait_existing_task(
                    pending,
                    MEDIA_WAIT_TIMEOUT - FIRST_BYTE_TIMEOUT,
                )

        if not ready:
            await _close_iterator(iterator, pending)

            if attempt >= 2:
                yield _sse_error(
                    "Die Chat-Runtime antwortet weiterhin nicht. Bitte erneut versuchen.",
                    "stream_stalled",
                    retryable=True,
                )
                return

            snapshot = await asyncio.to_thread(_agent_diagnostics, agent_url)
            previous_pid = snapshot.get("agent_pid")
            recovery = await asyncio.to_thread(
                _request_recovery,
                agent_url,
                "chat_first_byte_timeout",
            )

            if not recovery.get("scheduled"):
                yield _sse_error(
                    "Die Chat-Runtime reagiert nicht und konnte nicht automatisch neu gestartet werden.",
                    "recovery_blocked",
                    retryable=True,
                )
                return

            ready_after_restart = await asyncio.to_thread(
                _agent_ready_with_new_pid,
                agent_url,
                previous_pid,
                RECOVERY_READY_TIMEOUT,
            )
            if not ready_after_restart:
                yield _sse_error(
                    "Der Agent wurde neu gestartet, ist aber noch nicht wieder bereit.",
                    "recovery_timeout",
                    retryable=True,
                )
                return

            continue

        try:
            first = await pending
        except StopAsyncIteration:
            await _close_iterator(iterator)
            yield _sse_error(
                "Der Chat-Stream wurde ohne Antwort beendet.",
                "empty_stream",
                retryable=True,
            )
            return

        emitted = True
        yield first

        while True:
            ready, pending = await _wait_for_next(iterator, STREAM_STALL_TIMEOUT)
            if not ready:
                snapshot = await asyncio.to_thread(_agent_diagnostics, agent_url)
                await _close_iterator(iterator, pending)

                if not _media_is_active(snapshot):
                    await asyncio.to_thread(
                        _request_recovery,
                        agent_url,
                        "chat_stream_stalled_after_output",
                    )

                yield _sse_error(
                    "Die laufende Antwort ist hängen geblieben. Der Agent wird wiederhergestellt; bitte die Anfrage erneut senden.",
                    "stream_stalled_after_output",
                    retryable=True,
                )
                return

            try:
                chunk = await pending
            except StopAsyncIteration:
                await _close_iterator(iterator)
                return

            emitted = True
            yield chunk

    if not emitted:
        yield _sse_error(
            "Keine Antwort von der Chat-Runtime erhalten.",
            "empty_stream",
            retryable=True,
        )


async def _wait_existing_task(task, timeout: float):
    if timeout <= 0:
        return False, task
    done, _ = await asyncio.wait({task}, timeout=timeout)
    return task in done, task


def install_routes(
    app: FastAPI,
    *,
    stream_factory: Callable[[ReliableChatRequest], StreamingResponse],
    agent_url: str,
) -> None:
    paths = {
        getattr(route, "path", None)
        for route in app.router.routes
    }

    if "/api/chat/reliable-stream" not in paths:
        @app.post("/api/chat/reliable-stream")
        async def reliable_chat_stream(request: ReliableChatRequest):
            # Build one response up front solely to preserve media type/headers.
            template = stream_factory(request)
            headers = _copy_headers(template)
            await _close_iterator(template.body_iterator.__aiter__())

            headers["X-MLX-Reliability"] = "1"
            return StreamingResponse(
                _reliable_stream(
                    request,
                    stream_factory=stream_factory,
                    agent_url=agent_url,
                ),
                status_code=template.status_code,
                media_type=template.media_type or "text/event-stream",
                headers=headers,
            )

    if "/api/mlx/runtime/reliability" not in paths:
        @app.get("/api/mlx/runtime/reliability")
        async def runtime_reliability_proxy():
            return await asyncio.to_thread(_agent_diagnostics, agent_url)


__all__ = [
    "ReliableChatRequest",
    "install_routes",
]
