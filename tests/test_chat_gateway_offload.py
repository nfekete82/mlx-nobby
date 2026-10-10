"""Make sure synchronous chat routing does not block the async watchdog."""
import asyncio
import time
import unittest

from backend.chat_reliability_routes import _offloaded_iterator


class FakeResponse:
    @property
    def body_iterator(self):
        async def stream():
            yield b"data: {\"text\": \"OK\"}\\n\\n"
        return stream()


class GatewayOffloadTests(unittest.TestCase):
    def test_sync_gateway_setup_does_not_block_event_loop(self):
        async def scenario():
            def slow_factory(_request):
                time.sleep(0.12)
                return FakeResponse()

            iterator = _offloaded_iterator(object(), slow_factory)
            consumer = asyncio.create_task(iterator.__anext__())
            await asyncio.sleep(0.025)
            self.assertFalse(consumer.done(), "factory must still be running in thread")
            self.assertEqual(await asyncio.wait_for(consumer, 1), b"data: {\"text\": \"OK\"}\\n\\n")
            await iterator.aclose()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
