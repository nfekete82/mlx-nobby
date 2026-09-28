"""ASGI middleware that adds long-term memory to the normal chat stream.

The browser's standard text chat reaches ``/api/runtime/chat/stream`` directly
and therefore does not pass through ``ModelProvider``. Keeping this at the
agent boundary covers that path without modifying the large legacy app module.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os

from agent import memory_lifecycle


TARGET_PATH = "/api/runtime/chat/stream"
MAX_BODY_BYTES = 2 * 1024 * 1024
MEMORY_ENRICH_TIMEOUT_SECONDS = max(
    0.05,
    float(os.environ.get("MLX_MEMORY_CHAT_ENRICH_TIMEOUT", "1.5")),
)


class MemoryChatMiddleware:
    def __init__(self, app):
        self.app = app
        self._memory_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="mlx-memory-chat",
        )
        self._memory_future = None

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != TARGET_PATH:
            await self.app(scope, receive, send)
            return

        body = bytearray()
        more_body = True
        messages = []

        while more_body:
            event = await receive()
            messages.append(event)
            if event.get("type") != "http.request":
                continue
            chunk = event.get("body", b"")
            if chunk:
                body.extend(chunk)
            more_body = bool(event.get("more_body"))
            if len(body) > MAX_BODY_BYTES:
                await self._replay(scope, messages, receive, send)
                return

        replacement = bytes(body)
        try:
            payload = json.loads(replacement.decode("utf-8"))
            raw_messages = payload.get("messages")
            if isinstance(raw_messages, list):
                enriched = await self._enrich_messages(raw_messages)
                if enriched != raw_messages:
                    payload = dict(payload)
                    payload["messages"] = enriched
                    replacement = json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
        except Exception:
            # The memory layer must never make chat unavailable. Invalid JSON is
            # left to the existing request validation path.
            replacement = bytes(body)

        sent = False

        async def enriched_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {
                    "type": "http.request",
                    "body": replacement,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        await self.app(scope, enriched_receive, send)

    async def _enrich_messages(self, raw_messages):
        """Enrich within a strict latency budget and otherwise fail open.

        Semantic memory may need to cold-start the local embedding service or
        lazily backfill vectors. That work must never sit in front of the normal
        chat stream indefinitely. Only one enrichment job is allowed in flight;
        while it warms in the background, later chat requests simply proceed
        without memory context for that turn.
        """
        current = self._memory_future
        if current is not None and not current.done():
            return raw_messages

        future = self._memory_executor.submit(
            memory_lifecycle.enrich_messages,
            raw_messages,
        )
        self._memory_future = future
        wrapped = asyncio.wrap_future(future)

        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped),
                timeout=MEMORY_ENRICH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return raw_messages
        except Exception:
            return raw_messages

    async def _replay(self, scope, captured, receive, send):
        queue = list(captured)

        async def replay_receive():
            if queue:
                return queue.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)


__all__ = ["MemoryChatMiddleware"]
