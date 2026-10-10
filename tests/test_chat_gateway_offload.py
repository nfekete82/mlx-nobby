"""Make sure synchronous chat routing does not block the async watchdog."""
import asyncio
import time
import unittest

from backend.chat_reliability_routes import (
    _offloaded_iterator,
    _has_current_information_query,
    FIRST_BYTE_TIMEOUT,
    RESEARCH_FIRST_BYTE_TIMEOUT,
)


class FakeResponse:
    @property
    def body_iterator(self):
        async def stream():
            yield b"data: {\"text\": \"OK\"}\\n\\n"
        return stream()


class GatewayOffloadTests(unittest.TestCase):
    def test_current_information_questions_receive_research_budget(self):
        class Request:
            messages = [{"role": "user", "content": "Welche neuen Elektroautos wurden 2026 vorgestellt?"}]

        self.assertTrue(_has_current_information_query(Request()))
        self.assertGreaterEqual(RESEARCH_FIRST_BYTE_TIMEOUT, FIRST_BYTE_TIMEOUT)
        self.assertGreater(RESEARCH_FIRST_BYTE_TIMEOUT, 30)

    def test_private_local_questions_keep_standard_budget(self):
        class Request:
            messages = [{"role": "user", "content": "Wie läuft mein lokales Repository 2026?"}]

        self.assertFalse(_has_current_information_query(Request()))

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
