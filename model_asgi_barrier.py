"""ASGI request/unload barrier. No automatic unload or startup changes."""

import asyncio
import time
from contextlib import asynccontextmanager


class ASGIModelBarrier:
    def __init__(self, app):
        self.app = app
        self.condition = asyncio.Condition()
        self.active = 0
        self.pending = 0
        self.unloading = False
        self.last_activity = time.monotonic()

    def snapshot(self):
        return {
            "active_requests": self.active,
            "pending_requests": self.pending,
            "unloading": self.unloading,
        }

    @asynccontextmanager
    async def request(self):
        async with self.condition:
            self.pending += 1
            try:
                while self.unloading:
                    await self.condition.wait()
                self.active += 1
                self.last_activity = time.monotonic()
            finally:
                self.pending -= 1
        try:
            yield
        finally:
            async with self.condition:
                self.active -= 1
                self.last_activity = time.monotonic()
                self.condition.notify_all()

    @asynccontextmanager
    async def unload(self):
        async with self.condition:
            while self.unloading:
                await self.condition.wait()
            self.unloading = True
            try:
                while self.active:
                    await self.condition.wait()
            except BaseException:
                self.unloading = False
                self.condition.notify_all()
                raise
        try:
            yield
        finally:
            async with self.condition:
                self.unloading = False
                self.condition.notify_all()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        route = scope.get("path", "")
        method = scope.get("method", "").upper()

        # Health and discovery are read-only and do not execute models.
        if method == "GET" and route in (
            "/health", "/models", "/v1/models", "/metrics", "/v1/metrics"
        ):
            await self.app(scope, receive, send)
            return

        # The upstream MLX-VLM unload endpoint runs exclusively.
        if method == "POST" and route == "/unload":
            async with self.unload():
                await self.app(scope, receive, send)
            return

        # Retain the ticket until the entire ASGI response completes.
        async with self.request():
            await self.app(scope, receive, send)
