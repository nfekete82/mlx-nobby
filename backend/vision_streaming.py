"""Opt-in vision SSE relay.

Never substitute an empty/unsupported stream for a completed vision answer.
Retry the unchanged non-streaming bridge only if no answer text was emitted.
Once visible text was emitted, surface errors rather than generating duplicates.
"""
from __future__ import annotations

import json
import urllib.request


def _error_event():
    return 'event: error\ndata: {"error": "Vision stream interrupted"}\n\n'


def relay_vision_stream(stream_request, legacy_factory, *, timeout=60, opener=None):
    """Yield frontend SSE events, falling back only before first visible token.

    Parsing is bounded to individual upstream SSE frames. The old nonstream
    generator owns its own exception handling, payload, metrics and done event.
    """
    open_response = opener or urllib.request.urlopen
    visible = False
    done = False
    should_fallback = False
    event_name = ""
    data_lines = []

    def read_event():
        nonlocal event_name, data_lines
        event = event_name
        payload = "\n".join(data_lines)
        event_name, data_lines = "", []
        return event, payload

    try:
        with open_response(stream_request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/event-stream" not in content_type:
                should_fallback = True
            else:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        event, payload = read_event()
                        if not payload and not event:
                            continue
                        if event == "error":
                            if visible:
                                yield f'event: error\ndata: {payload}\n\n'
                                return
                            should_fallback = True
                            break
                        if event == "done" or payload == "[DONE]":
                            if visible:
                                yield "event: done\ndata: {}\n\n"
                                done = True
                            else:
                                should_fallback = True
                            break
                        if event == "metrics":
                            if visible:
                                yield f'event: metrics\ndata: {payload}\n\n'
                            continue
                        try:
                            item = json.loads(payload)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(item, dict):
                            continue
                        if (item.get("type") in {"content", "reasoning"}
                                and isinstance(item.get("text"), str)
                                and item["text"]):
                            visible = True
                            yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
                    elif line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" "))
    except Exception:
        # The stream might fail before or after the first chunk. It is only
        # safe to repeat the request if nothing was displayed to the user.
        if visible:
            yield _error_event()
            return
        should_fallback = True

    if done:
        return
    if visible:
        # Never replay a partially delivered answer after premature EOF.
        yield _error_event()
    elif should_fallback or not visible:
        yield from legacy_factory()
