import asyncio
import unittest

from model_asgi_barrier import ASGIModelBarrier


class ASGIBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.unload_entered = asyncio.Event()

        async def fake_app(scope, receive, send):
            route = scope["path"]
            if route == "/unload":
                self.unload_entered.set()
            elif route == "/v1/chat/completions":
                self.entered.set()
                await self.release.wait()

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await send({
                "type": "http.response.body",
                "body": b"ok",
                "more_body": False,
            })

        self.barrier = ASGIModelBarrier(fake_app)

    async def call(self, route, method="POST"):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"",
                    "more_body": False}

        async def send(message):
            sent.append(message)

        await self.barrier(
            {"type": "http", "path": route, "method": method},
            receive, send
        )
        return sent

    async def test_stream_blocks_unload_until_completion(self):
        chat = asyncio.create_task(
            self.call("/v1/chat/completions"))
        await asyncio.wait_for(self.entered.wait(), 1)
        self.assertEqual(self.barrier.snapshot()["active_requests"], 1)

        unload = asyncio.create_task(self.call("/unload"))
        await asyncio.sleep(0)
        self.assertFalse(self.unload_entered.is_set())

        self.release.set()
        await asyncio.wait_for(chat, 1)
        await asyncio.wait_for(unload, 1)
        self.assertTrue(self.unload_entered.is_set())
        self.assertEqual(self.barrier.snapshot()["active_requests"], 0)

    async def test_new_chat_waits_during_unload(self):
        async with self.barrier.unload():
            chat = asyncio.create_task(
                self.call("/v1/chat/completions"))
            await asyncio.sleep(0)
            self.assertFalse(self.entered.is_set())
            self.assertEqual(
                self.barrier.snapshot()["pending_requests"], 1)

        self.release.set()
        await asyncio.wait_for(chat, 1)
        self.assertTrue(self.entered.is_set())

    async def test_health_works_during_unload(self):
        async with self.barrier.unload():
            result = await asyncio.wait_for(
                self.call("/health", "GET"), 1)
            self.assertEqual(result[0]["status"], 200)

    async def test_exception_releases_ticket(self):
        async def broken(scope, receive, send):
            raise RuntimeError("test")

        barrier = ASGIModelBarrier(broken)
        with self.assertRaises(RuntimeError):
            await barrier(
                {"type": "http", "path": "/v1/chat/completions",
                 "method": "POST"},
                None, None
            )
        self.assertEqual(barrier.snapshot()["active_requests"], 0)
