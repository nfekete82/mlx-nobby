"""ASGI middleware that adds long-term memory to the normal chat stream.

The browser's standard text chat reaches ``/api/runtime/chat/stream`` directly
and therefore does not pass through ``ModelProvider``. Keeping this at the
agent boundary covers that path without modifying the large legacy app module.
"""

from __future__ import annotations

import json

from agent import memory_lifecycle


TARGET_PATH = "/api/runtime/chat/stream"
MAX_BODY_BYTES = 2 * 1024 * 1024


class MemoryChatMiddleware:
    def __init__(self, app):
        self.app = app

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
                enriched = memory_lifecycle.enrich_messages(raw_messages, observe=True)
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

    async def _replay(self, scope, captured, receive, send):
        queue = list(captured)

        async def replay_receive():
            if queue:
                return queue.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)


__all__ = ["MemoryChatMiddleware"]
