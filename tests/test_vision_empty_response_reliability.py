import asyncio

from fastapi.responses import StreamingResponse

from backend import chat_reliability_routes as web_routes


class _StreamFactory:
    def __init__(self, generator_factory):
        self.generator_factory = generator_factory
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        return StreamingResponse(
            self.generator_factory(),
            media_type="text/event-stream",
        )


async def _collect(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
        for chunk in chunks
    )


def test_named_sse_error_matches_frontend_protocol():
    event = web_routes._sse_error(
        "Vision model returned no content.",
        "empty_response",
        retryable=True,
    )

    assert event.startswith(b"event: error\n")
    assert b'"code": "empty_response"' in event


def test_done_without_content_becomes_visible_error():
    async def empty_vision_response():
        yield b'event: metrics\ndata: {"trace_id":"vision-empty"}\n\n'
        yield b'event: done\ndata: {}\n\n'

    request = web_routes.ReliableChatRequest(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "ich brauche den perfekten prompt fuer ltx 2.5 "
                            "damit sie einen kussmund macht laechelt und den "
                            "kopf leicht bewegt"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,ZmFrZQ==",
                        },
                    },
                ],
            }
        ]
    )
    factory = _StreamFactory(empty_vision_response)

    body = asyncio.run(
        _collect(
            web_routes._reliable_stream(
                request,
                stream_factory=factory,
                agent_url="http://agent",
            )
        )
    )

    assert b"event: error\n" in body
    assert b'"code": "empty_response"' in body
    assert factory.calls == 1


def test_content_response_does_not_get_empty_response_error():
    async def normal_vision_response():
        yield b'data: {"type":"content","text":"Use a subtle head tilt."}\n\n'
        yield b'event: done\ndata: {}\n\n'

    request = web_routes.ReliableChatRequest(
        messages=[{"role": "user", "content": "Describe image"}]
    )
    factory = _StreamFactory(normal_vision_response)

    body = asyncio.run(
        _collect(
            web_routes._reliable_stream(
                request,
                stream_factory=factory,
                agent_url="http://agent",
            )
        )
    )

    assert b"Use a subtle head tilt." in body
    assert b'"code": "empty_response"' not in body
