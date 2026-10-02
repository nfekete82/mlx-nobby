"""Stateless OpenAI transport. The host supplies the existing runtime lease.

No agent, tools, memory, chat persistence or client credentials are invoked.
Every completion uses native upstream SSE, including non-stream requests, so
closing the downstream connection can cancel the native token iterator.
"""

import asyncio
from contextlib import contextmanager
import http.client
import json
import queue
import socket
import threading
import time
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, model_validator
from starlette.responses import JSONResponse, Response
from backend import observability


ROLES = ("coding", "chat", "agent")


class ModelUnavailable(RuntimeError):
    pass


def error(message, code, status=400):
    return JSONResponse({"error": {"message": message, "type": (
        "invalid_request_error" if status < 500 else "server_error"
    ), "code": code}}, status_code=status)


class Function(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1)
    description: StrictStr | None = None
    parameters: dict = Field(default_factory=dict)
    strict: StrictBool | None = None


class Tool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: StrictStr
    function: Function

    @model_validator(mode="after")
    def function_only(self):
        if self.type != "function":
            raise ValueError("Only function tools are supported")
        return self


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: StrictStr
    content: StrictStr | list[dict] | None = None
    name: StrictStr | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: StrictStr | None = None
    reasoning_content: StrictStr | None = None

    @model_validator(mode="after")
    def validate_message(self):
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Unsupported message role")
        if isinstance(self.content, list):
            if not self.content or any(
                set(part) != {"type", "text"} or part.get("type") != "text"
                or not isinstance(part.get("text"), str) for part in self.content
            ):
                raise ValueError("Only text content parts are supported")
        if self.content is None and not (self.role == "assistant" and self.tool_calls):
            raise ValueError("Message content is required")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool results require tool_call_id")
        if self.tool_calls is not None:
            if self.role != "assistant" or not self.tool_calls:
                raise ValueError("Only assistant messages may contain tool calls")
            for call in self.tool_calls:
                fn = call.get("function")
                if (call.get("type") != "function" or not isinstance(call.get("id"), str)
                        or not call["id"] or not isinstance(fn, dict)
                        or not isinstance(fn.get("name"), str) or not fn["name"]
                        or not isinstance(fn.get("arguments"), str)):
                    raise ValueError("Invalid assistant tool call")
                json.loads(fn["arguments"])
        return self


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: StrictStr = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    stream: StrictBool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    max_completion_tokens: StrictInt | None = Field(default=None, gt=0)
    stop: StrictStr | list[StrictStr] | None = None
    tools: list[Tool] | None = None
    tool_choice: StrictStr | dict | None = None
    stream_options: dict | None = None
    top_p: float | None = Field(default=None, ge=0, le=1)
    seed: StrictInt | None = None
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)

    @model_validator(mode="after")
    def validate_options(self):
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("Specify only one output token limit")
        stops = [self.stop] if isinstance(self.stop, str) else self.stop
        if stops is not None and (not stops or len(stops) > 4 or any(not s for s in stops)):
            raise ValueError("stop must contain one to four nonempty strings")
        if self.stream_options is not None and (
            set(self.stream_options) != {"include_usage"}
            or not isinstance(self.stream_options["include_usage"], bool)
        ):
            raise ValueError("Only stream_options.include_usage is supported")
        names = {tool.function.name for tool in self.tools or []}
        if len(names) != len(self.tools or []):
            raise ValueError("Tool names must be unique")
        if isinstance(self.tool_choice, str):
            if self.tool_choice not in {"none", "auto", "required"}:
                raise ValueError("Invalid tool_choice")
            if self.tool_choice == "required" and not names:
                raise ValueError("tool_choice requires tools")
        elif self.tool_choice is not None:
            choice = self.tool_choice
            fn = choice.get("function", {})
            if (set(choice) != {"type", "function"} or choice["type"] != "function"
                    or not isinstance(fn, dict) or set(fn) != {"name"}
                    or not isinstance(fn["name"], str) or fn["name"] not in names):
                raise ValueError("Invalid function tool_choice")
        pending = set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Tool result must match a preceding assistant tool call")
                pending.remove(message.tool_call_id)
            else:
                if pending:
                    raise ValueError("Missing tool results")
                pending.update(call["id"] for call in message.tool_calls or [])
        if pending:
            raise ValueError("Missing tool results")
        return self


class Transfer:
    """One owner thread for coordinator/RLock; bounded queue and socket abort."""

    def __init__(self, worker):
        self.cancel = threading.Event()
        self.items = queue.Queue(maxsize=32)
        self.connection = None
        self.socket = None
        self.metrics = None
        self.thread = threading.Thread(target=self._run, args=(worker,), daemon=True)

    def put(self, item):
        while not self.cancel.is_set():
            try:
                self.items.put(item, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def abort(self):
        self.cancel.set()
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _run(self, worker):
        try:
            worker(self)
        except ModelUnavailable:
            self.put(("error", (503, "Configured model unavailable", "model_unavailable")))
        except Exception:
            # Upstream diagnostics can contain local paths or client payloads.
            self.put(("error", (503, "Runtime unavailable", "runtime_unavailable")))
        finally:
            if self.metrics is not None and self.metrics.metric["status"] == "running":
                self.metrics.fail("cancelled" if self.cancel.is_set() else "runtime_unavailable")
            if self.connection is not None:
                self.connection.close()
            if self.socket is not None:
                self.socket.close()
            self.put(("end", None))

    async def next(self):
        while not self.cancel.is_set():
            try:
                return self.items.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
        raise asyncio.CancelledError

    def open(self, url, payload=None):
        target = urlsplit(url)
        self.connection = http.client.HTTPConnection(target.hostname, target.port, timeout=900)
        if self.cancel.is_set():
            raise RuntimeError("cancelled")
        self.connection.connect()
        self.socket = self.connection.sock
        # Keep the socket until body consumption ends, so abort can shutdown a
        # blocked read even when upstream announces Connection: close.
        if self.cancel.is_set():
            raise RuntimeError("cancelled")
        self.connection.request("POST" if payload is not None else "GET", target.path,
                                body=json.dumps(payload).encode() if payload is not None else None,
                                headers={"Content-Type": "application/json"})
        response = self.connection.getresponse()
        if response.status >= 400:
            self.put(("error", (response.status, "Upstream rejected request", "upstream_error")))
            return None
        return response


class TransferResponse(Response):
    """Monitor disconnect also before headers and for non-stream completions."""

    def __init__(self, transfer, stream):
        super().__init__()
        self.transfer, self.stream = transfer, stream

    async def __call__(self, scope, receive, send):
        async def disconnected():
            while True:
                if (await receive())["type"] == "http.disconnect":
                    self.transfer.abort()
                    return

        async def deliver():
            started = False
            while True:
                kind, value = await self.transfer.next()
                if kind == "error":
                    status, message, code = value
                    if not started:
                        await error(message, code, status)(scope, receive, send)
                    else:
                        body = error(message, code, status).body
                        await send({"type": "http.response.body", "body": b"data: " + body + b"\n\n", "more_body": True})
                        await send({"type": "http.response.body", "body": b"data: [DONE]\n\n"})
                    return
                if kind == "headers":
                    if not self.stream:
                        continue
                    await send({"type": "http.response.start", "status": 200, "headers": [
                        (b"content-type", b"text/event-stream"), (b"cache-control", b"no-cache"),
                        (b"x-accel-buffering", b"no"),
                    ]})
                    started = True
                elif kind == "body":
                    if not started:
                        await send({"type": "http.response.start", "status": 200,
                                    "headers": [(b"content-type", b"application/json")]})
                        started = True
                    await send({"type": "http.response.body", "body": value, "more_body": True})
                elif kind == "end":
                    if not started:
                        await error("Incomplete upstream response", "invalid_response", 502)(scope, receive, send)
                    else:
                        await send({"type": "http.response.body", "body": b""})
                    return

        self.transfer.thread.start()
        listener = asyncio.create_task(disconnected())
        sender = asyncio.create_task(deliver())
        try:
            await asyncio.wait((listener, sender), return_when=asyncio.FIRST_COMPLETED)
            if sender.done():
                await sender
        finally:
            self.transfer.abort()
            listener.cancel()
            sender.cancel()
            await asyncio.gather(listener, sender, return_exceptions=True)


@contextmanager
def runtime_session(host, transfer, role):
    with host.runtime_coordinator.chat_runtime(transfer.cancel):
        while not transfer.cancel.is_set():
            if host.MODEL_RUNTIME_LOCK.acquire(timeout=0.05):
                break
        else:
            raise RuntimeError("cancelled")
        try:
            if transfer.cancel.is_set():
                raise RuntimeError("cancelled")
            resolved = host.resolve_model_role(role)
            metadata = host.detect_model_metadata(resolved.get("repo"))
            if not resolved.get("repo") or resolved.get("available") is False or metadata.get("available") is False:
                raise ModelUnavailable
            yield host.ensure_model_for_role(role)["resolved"]
        finally:
            host.MODEL_RUNTIME_LOCK.release()


def combine(chunks, model):
    """Assemble native OpenAI deltas, including indexed function arguments."""
    result = None
    message = {"role": "assistant", "content": ""}
    calls = {}
    finish = None
    usage = None
    for chunk in chunks:
        if result is None:
            result = {k: chunk[k] for k in ("id", "created")}
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk["choices"]:
            finish = choice.get("finish_reason") or finish
            delta = choice.get("delta", {})
            for key in ("content", "reasoning_content", "reasoning"):
                if isinstance(delta.get(key), str):
                    message[key] = message.get(key, "") + delta[key]
            for call in delta.get("tool_calls") or []:
                item = calls.setdefault(call["index"], {"id": "", "type": "function",
                                                        "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    item["id"] = call["id"]
                for key in ("name", "arguments"):
                    item["function"][key] += call.get("function", {}).get(key) or ""
    if result is None or finish is None:
        raise ValueError("Incomplete completion")
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
        message["content"] = message["content"] or None
    result.update(object="chat.completion", model=model,
                  choices=[{"index": 0, "message": message, "finish_reason": finish}])
    if usage is not None:
        result["usage"] = usage
    return result


class StopFilter:
    """Hold only possible suffixes of literal stop strings across text deltas.

    This never interprets tool output or model markup. A detected literal stop
    closes native SSE immediately; usage is omitted because the runtime never
    finalized it. Native EOS/length flushes any unmatched suffix.
    """

    def __init__(self, stop):
        self.stops = [stop] if isinstance(stop, str) else (stop or [])
        self.pending = ""
        self.stopped = False

    def apply(self, chunk):
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            text = delta.get("content")
            if not self.stops or not isinstance(text, str):
                if choice.get("finish_reason") and self.pending:
                    delta["content"] = self.pending
                    self.pending = ""
                continue
            self.pending += text
            hits = [self.pending.find(stop) for stop in self.stops if stop in self.pending]
            if hits:
                delta["content"] = self.pending[:min(hits)]
                self.pending = ""
                choice["finish_reason"] = "stop"
                self.stopped = True
                continue
            keep = 0
            if not choice.get("finish_reason"):
                for stop in self.stops:
                    for length in range(1, min(len(stop), len(self.pending) + 1)):
                        if self.pending.endswith(stop[:length]):
                            keep = max(keep, length)
            delta["content"] = self.pending[:-keep] if keep else self.pending
            self.pending = self.pending[-keep:] if keep else ""
        return chunk


def install_routes(app, *, host=None, agent_url=None):
    """Install either the web relay or the role-aware native inference routes."""
    @app.get("/v1/models")
    def models():
        if host is None:
            def relay(transfer):
                response = transfer.open(agent_url + "/v1/models")
                if response is not None:
                    transfer.put(("body", response.read()))
            return TransferResponse(Transfer(relay), False)
        try:
            data = []
            for role in ROLES:
                resolved = host.resolve_model_role(role)
                metadata = host.detect_model_metadata(resolved.get("repo"))
                if (resolved.get("repo") and resolved.get("available") is not False
                        and metadata.get("available") is not False):
                    data.append({"id": "mlx-nobby/" + role, "object": "model", "owned_by": "mlx-nobby"})
            return {"object": "list", "data": data}
        except Exception:
            return error("Model configuration unavailable", "model_unavailable", 503)

    @app.post("/v1/chat/completions")
    async def complete(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return error("Content-Type must be application/json", "invalid_content_type", 415)
        try:
            completion = Completion.model_validate(await request.json())
        except (ValueError, ValidationError):
            return error("Invalid chat completion request or unsupported fields", "invalid_request")
        role = completion.model.removeprefix("mlx-nobby/")
        if completion.model != "mlx-nobby/" + role or role not in ROLES:
            return error("Unknown model ID", "model_not_found", 404)

        def worker(transfer):
            payload = completion.model_dump(exclude_none=True)
            if host is None:
                response = transfer.open(agent_url + "/v1/chat/completions", payload)
                if response is None:
                    return
                transfer.put(("headers", None))
                if completion.stream:
                    while not transfer.cancel.is_set():
                        line = response.readline()
                        if not line:
                            break
                        if not transfer.put(("body", line)):
                            break
                        if line.startswith(b"data:") and line[5:].strip() == b"[DONE]":
                            transfer.put(("body", b"\n"))
                            break
                else:
                    transfer.put(("body", response.read()))
                return

            transfer.metrics = observability.ModelCallMetrics(
                purpose="external.chat.completions", role=role,
                messages=payload["messages"], context_sources={},
            )
            wait_started = time.monotonic()
            with runtime_session(host, transfer, role) as resolved:
                transfer.metrics.set_queue_wait((time.monotonic() - wait_started) * 1000)
                transfer.metrics.set_model(model=resolved.get("repo"), role=role, alias=resolved.get("alias"))
                if not resolved.get("repo") or resolved.get("available") is False:
                    transfer.put(("error", (503, "Configured model unavailable", "model_unavailable")))
                    return
                payload["model"] = resolved["repo"]
                payload.pop("stop", None)
                if "max_completion_tokens" in payload:
                    payload["max_tokens"] = payload.pop("max_completion_tokens")
                payload["stream"] = True
                payload["stream_options"] = {"include_usage": True}
                url = f"http://127.0.0.1:{int(host.load_config().get('PORT', 8000))}/v1/chat/completions"
                connect_started = time.monotonic()
                response = transfer.open(url, payload)
                transfer.metrics.set_upstream_connect((time.monotonic() - connect_started) * 1000)
                if response is None:
                    return
                transfer.put(("headers", None))
                chunks = []
                done = False
                stop_filter = StopFilter(completion.stop)
                usage, finish = None, None
                output_characters = 0
                while not transfer.cancel.is_set():
                    line = response.readline()
                    if not line:
                        break
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        done = True
                        if completion.stream:
                            transfer.put(("body", b"data: [DONE]\n\n"))
                        break
                    chunk = json.loads(data)
                    if "error" in chunk:
                        raise ValueError("Upstream stream failed")
                    chunk["model"] = completion.model
                    chunk = stop_filter.apply(chunk)
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"):
                            transfer.metrics.mark_first_token()
                        output_characters += len(delta.get("content") or "")
                        finish = choice.get("finish_reason") or finish
                    if completion.stream:
                        if chunk.get("usage") and not (completion.stream_options or {}).get("include_usage"):
                            continue
                        transfer.put(("body", b"data: " + json.dumps(chunk).encode() + b"\n\n"))
                    else:
                        chunks.append(chunk)
                    if stop_filter.stopped:
                        done = True
                        try:
                            transfer.socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        if completion.stream:
                            transfer.put(("body", b"data: [DONE]\n\n"))
                        break
                if not transfer.cancel.is_set():
                    if not done:
                        raise ValueError("Truncated upstream SSE")
                    if not completion.stream:
                        transfer.put(("body", json.dumps(combine(chunks, completion.model)).encode()))
                    transfer.metrics.finish(usage=usage, output_characters=output_characters, finish_reason=finish)

        return TransferResponse(Transfer(worker), completion.stream)
