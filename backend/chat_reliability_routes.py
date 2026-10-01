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
VISION_FIRST_BYTE_TIMEOUT = max(
    FIRST_BYTE_TIMEOUT,
    float(os.environ.get("MLX_CHAT_VISION_FIRST_BYTE_TIMEOUT", "60")),
)
VISION_HEARTBEAT_INTERVAL = 5.0
VISION_HEARTBEAT = b": vision request pending\n\n"

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
        result = _json_request(
            "POST",
            agent_url.rstrip("/") + "/api/runtime/reliability/recover",
            {"reason": reason, "force": False},
            timeout=5,
        )
        if result.get("scheduled"):
            from backend.routing_observatory import observe_fallback
            observe_fallback("runtime_recovery")
        return result
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
    return (
        "event: error\n"
        f"data: {payload}\n\n"
    ).encode("utf-8")


class _SemanticSseTracker:
    """Track whether an SSE stream produced actual assistant output.

    Metrics, source metadata and a terminal ``done`` event are transport
    bookkeeping, not a model answer. Without this distinction a vision backend
    can return an empty OpenAI response and still look successful to the
    reliability layer, leaving a blank assistant bubble in the UI.
    """

    def __init__(self):
        self.buffer = ""
        self.has_output = False
        self.has_error = False

    def feed(self, chunk) -> None:
        if isinstance(chunk, bytes):
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = str(chunk)

        self.buffer += text.replace("\r\n", "\n")

        while "\n\n" in self.buffer:
            event, self.buffer = self.buffer.split("\n\n", 1)
            self._observe(event)

    def finish(self) -> None:
        if self.buffer.strip():
            self._observe(self.buffer)
        self.buffer = ""

    def _observe(self, event: str) -> None:
        event_name = "message"
        data_lines = []

        for line in event.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip().lower()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if event_name == "error":
            self.has_error = True
            return

        if not data_lines:
            return

        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        if payload.get("error"):
            self.has_error = True
            return

        text = str(payload.get("text") or "").strip()
        payload_type = str(payload.get("type") or "").strip().lower()

        if text and (
            payload_type in {"content", "reasoning"}
            or event_name == "message"
        ):
            self.has_output = True

    @property
    def completed_meaningfully(self) -> bool:
        return self.has_output or self.has_error


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


def _has_vision_input(request: ReliableChatRequest) -> bool:
    # Match the gateway's image_url handling, including images in history.
    for message in request.messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if isinstance(url, str) and url:
                return True
    return False


async def _vision_iterator(request, stream_factory):
    # The gateway factory performs synchronous context/routing HTTP calls.
    # Keep those off the event loop so the watchdog and heartbeats can run.
    response = await asyncio.to_thread(stream_factory, request)
    iterator = response.body_iterator.__aiter__()
    try:
        async for chunk in iterator:
            yield chunk
    finally:
        await _close_iterator(iterator)


async def _wait_with_heartbeats(task, timeout: float, vision: bool):
    """Wait on ONE upstream read; transport heartbeats never reset its deadline."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield False
            return
        interval = min(remaining, VISION_HEARTBEAT_INTERVAL) if vision else remaining
        done, _ = await asyncio.wait({task}, timeout=interval)
        if task in done:
            yield True
            return
        if time.monotonic() >= deadline:
            yield False
            return
        yield None  # Heartbeat only, not upstream activity or model output.


def _media_is_active(snapshot: dict) -> bool:
    workload = (snapshot.get("lease") or {}).get("active_workload")
    return workload in {"image", "video"}


async def _reliable_stream(
    request: ReliableChatRequest,
    *,
    stream_factory: Callable[[ReliableChatRequest], StreamingResponse],
    agent_url: str,
):
    emitted = False
    attempt = 0
    vision = _has_vision_input(request)
    first_timeout = VISION_FIRST_BYTE_TIMEOUT if vision else FIRST_BYTE_TIMEOUT

    while attempt < 2:
        attempt += 1
        prefill_deadline = time.monotonic() + first_timeout
        if vision:
            iterator = _vision_iterator(request, stream_factory).__aiter__()
        else:
            response = stream_factory(request)
            iterator = response.body_iterator.__aiter__()
        semantic = _SemanticSseTracker()
        pending = None

        try:
            if vision:
                yield VISION_HEARTBEAT
            pending = asyncio.create_task(iterator.__anext__())
            async for ready in _wait_with_heartbeats(
                pending,
                max(0.0, prefill_deadline - time.monotonic()) if vision else first_timeout,
                vision,
            ):
                if ready is None:
                    yield VISION_HEARTBEAT

            if not ready:
                snapshot = await asyncio.to_thread(_agent_diagnostics, agent_url)

                if _media_is_active(snapshot):
                    prefill_deadline += max(0.0, MEDIA_WAIT_TIMEOUT - first_timeout)
                    media_remaining = (
                        max(0.0, prefill_deadline - time.monotonic())
                        if vision else max(0.0, MEDIA_WAIT_TIMEOUT - first_timeout)
                    )
                    async for ready in _wait_with_heartbeats(pending, media_remaining, vision):
                        if ready is None:
                            yield VISION_HEARTBEAT

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
            except Exception as exc:
                await _close_iterator(iterator)
                yield _sse_error(
                    f"Chat-Stream konnte nicht gestartet werden: {exc}",
                    "stream_start_failed",
                    retryable=True,
                )
                return

            semantic.feed(first)
            emitted = True
            yield first

            while True:
                prefill = vision and not semantic.completed_meaningfully
                timeout = (
                    max(0.0, prefill_deadline - time.monotonic())
                    if prefill else STREAM_STALL_TIMEOUT
                )
                pending = asyncio.create_task(iterator.__anext__())
                async for ready in _wait_with_heartbeats(pending, timeout, vision):
                    if ready is None:
                        yield VISION_HEARTBEAT
                if not ready:
                    snapshot = await asyncio.to_thread(_agent_diagnostics, agent_url)
                    await _close_iterator(iterator, pending)

                    if not _media_is_active(snapshot):
                        await asyncio.to_thread(
                            _request_recovery,
                            agent_url,
                            "chat_first_byte_timeout" if prefill else "chat_stream_stalled_after_output",
                        )

                    yield _sse_error(
                        (
                            "Die Chat-Runtime liefert weiterhin keinen Inhalt. Bitte erneut versuchen."
                            if prefill else
                            "Die laufende Antwort ist hängen geblieben. Der Agent wird wiederhergestellt; bitte die Anfrage erneut senden."
                        ),
                        "stream_stalled" if prefill else "stream_stalled_after_output",
                        retryable=True,
                    )
                    return

                try:
                    chunk = await pending
                except StopAsyncIteration:
                    semantic.finish()
                    await _close_iterator(iterator)

                    if not semantic.completed_meaningfully:
                        yield _sse_error(
                            "Das Modell hat die Anfrage beendet, ohne Inhalt zu liefern. Bitte erneut versuchen.",
                            "empty_response",
                            retryable=True,
                        )
                    return
                except Exception as exc:
                    await _close_iterator(iterator)
                    yield _sse_error(
                        f"Die laufende Antwort wurde unterbrochen: {exc}",
                        "stream_interrupted",
                        retryable=True,
                    )
                    return

                semantic.feed(chunk)
                emitted = True
                yield chunk
        finally:
            await _close_iterator(iterator, pending)

    if not emitted:
        yield _sse_error(
            "Keine Antwort von der Chat-Runtime erhalten.",
            "empty_stream",
            retryable=True,
        )


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
            return StreamingResponse(
                _reliable_stream(
                    request,
                    stream_factory=stream_factory,
                    agent_url=agent_url,
                ),
                status_code=200,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-MLX-Reliability": "1",
                },
            )

    if "/api/mlx/runtime/reliability" not in paths:
        @app.get("/api/mlx/runtime/reliability")
        async def runtime_reliability_proxy():
            return await asyncio.to_thread(_agent_diagnostics, agent_url)


__all__ = [
    "ReliableChatRequest",
    "install_routes",
]
