"""Synchronous agent-model contract and the existing local MLX transport."""

from dataclasses import dataclass, field
from contextlib import nullcontext, contextmanager
import json
import time
from typing import Callable, ContextManager, Protocol
import urllib.error
import urllib.request

from agent import memory_lifecycle, system_clock
from agent.run_state import RunContext
from backend import observability


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict]
    max_tokens: int = 1200
    temperature: float = 0.1
    role: str = "agent"


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    role: str
    usage: dict
    finish_reason: str | None = None
    telemetry: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest, *, run_context: RunContext | None = None) -> ModelResponse:
        ...


def _check_cancelled(context):
    if context is not None and context.cancelled:
        raise ProviderError("cancelled", "Agent-Modellaufruf wurde abgebrochen")


@contextmanager
def _model_lock(lock, context):
    """Keep production lock waits cancellable without changing lock order."""
    if context is None or not hasattr(lock, "acquire"):
        with lock:
            yield
        return
    while not lock.acquire(timeout=.05):
        _check_cancelled(context)
    try:
        _check_cancelled(context)
        yield
    finally:
        lock.release()


def _memory_allowed(request: ModelRequest) -> bool:
    """Keep dynamic context out of strict machine-output/transformation prompts."""
    if request.role not in {"chat", "agent", "coding"}:
        return False
    system_text = "\n".join(
        str(message.get("content") or "")
        for message in request.messages
        if message.get("role") == "system"
        and isinstance(message.get("content"), str)
    ).casefold()
    strict_markers = (
        "return exactly one json",
        "return json only",
        "literal translator",
        "repair the supplied output",
        "translate the user's prompt into english and nothing else",
    )
    return not any(marker in system_text for marker in strict_markers)


def _with_system_clock(request: ModelRequest) -> ModelRequest:
    """Add a fresh native-host clock snapshot to user-facing model turns."""
    if not _memory_allowed(request):
        return request
    try:
        clock_context = system_clock.context()
    except Exception:
        # Clock enrichment is useful context, never a reason to break inference.
        return request

    if not clock_context:
        return request

    messages = [dict(message) for message in request.messages]
    for index, message in enumerate(messages):
        if message.get("role") != "system" or not isinstance(message.get("content"), str):
            continue
        content = message.get("content", "").strip()
        messages[index]["content"] = (
            content + "\n\n" + clock_context if content else clock_context
        )
        break
    else:
        messages.insert(0, {"role": "system", "content": clock_context})

    return ModelRequest(
        messages=messages,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        role=request.role,
    )


def _with_memory(request: ModelRequest, run_context: RunContext | None) -> ModelRequest:
    if not _memory_allowed(request):
        return request
    try:
        chat_id = getattr(run_context, "chat_id", None) if run_context is not None else None
        messages = memory_lifecycle.enrich_messages(
            request.messages,
            source_chat_id=chat_id,
            observe=True,
        )
    except Exception:
        # Memory must never make the core model path unavailable. A corrupt or
        # temporarily locked local database simply degrades to normal chat.
        return request
    if messages == request.messages:
        return request
    return ModelRequest(
        messages=messages,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        role=request.role,
    )


class MLXProvider:
    """Uses the host's existing role resolver, shared runtime lock and config.

    Cancellation is cooperative at operation boundaries; an in-flight blocking
    HTTP request (or lock wait) still has to finish before it can be observed.
    """

    def __init__(
        self,
        runtime_lock: ContextManager,
        ensure_model_for_role: Callable[[str], dict],
        load_config: Callable[[], dict],
        *,
        runtime_lease: Callable[[RunContext | None], ContextManager] | None = None,
    ):
        self.runtime_lock = runtime_lock
        self.ensure_model_for_role = ensure_model_for_role
        self.load_config = load_config
        self.runtime_lease = runtime_lease or (lambda _context: nullcontext())

    def complete(self, request: ModelRequest, *, run_context: RunContext | None = None) -> ModelResponse:
        _check_cancelled(run_context)
        request = _with_system_clock(request)
        request = _with_memory(request, run_context)
        metrics = observability.ModelCallMetrics(
            purpose=observability.current_call_purpose("agent.call"),
            role=request.role,
            messages=request.messages,
            context_sources=observability.current_context_sources(
                observability.message_context_counts(request.messages, "tool_agent")
            ),
        )
        wait_started = time.monotonic()
        try:
            # Production injects the same lease used by chat streaming. Take
            # it BEFORE the model lock; role resolution also enters the lease.
            from agent.lease_diagnostics import observed_agent_lease, acquired_agent_lease
            from runtime_coordinator import lease_workload
            with lease_workload(request.role), observed_agent_lease(request.role) as (lease_evidence, lease_ident):
                with self.runtime_lease(run_context) as central_evidence:
                    lease_wait_ms = round((time.monotonic() - wait_started) * 1000, 2)
                    acquired_agent_lease(lease_ident, request.role)
                    lock_started = time.monotonic()
                    with _model_lock(self.runtime_lock, run_context):
                        lock_wait_ms = round((time.monotonic() - lock_started) * 1000, 2)
                        metrics.set_queue_wait((time.monotonic() - wait_started) * 1000)
                        _check_cancelled(run_context)
                        result = self._complete(request, run_context, metrics)
                        result.telemetry["queue_wait_ms"] = round(lease_wait_ms + lock_wait_ms, 2)
                        result.telemetry["lease_wait_ms"] = lease_wait_ms
                        result.telemetry["lock_wait_ms"] = lock_wait_ms
                        result.telemetry.update(lease_evidence)
                        # No contention means no blocking owner. A concurrent
                        # agent holder is only a candidate, not proven owner.
                        if isinstance(central_evidence, dict):
                            for key in ("observed_holder_role", "observed_holder_age_ms"):
                                if key in central_evidence:
                                    result.telemetry[key] = central_evidence[key]
                        elif lease_wait_ms < 100:
                            result.telemetry["observed_holder_role"] = "none"
                        elif lease_evidence["observed_holder_role"] != "unknown":
                            result.telemetry["observed_holder_role"] = "possible_agent_holder"
                        return result
        except ProviderError as exc:
            metrics.fail(exc.code)
            raise
        except Exception as exc:
            if run_context is not None and run_context.cancelled:
                metrics.fail("cancelled")
                raise ProviderError("cancelled", "Agent-Modellaufruf wurde abgebrochen") from exc
            metrics.fail("provider_error")
            raise ProviderError("provider_error", str(exc)) from exc

    def _complete(self, request, context, metrics):
        setup_started = time.monotonic()
        try:
            runtime = self.ensure_model_for_role(request.role)
            role = runtime["resolved"]
            model = role.get("repo")
        except Exception as exc:
            raise ProviderError("model_unavailable", str(exc)) from exc
        _check_cancelled(context)
        if not model:
            raise ProviderError(
                "model_unavailable",
                "Für die Agent-Rolle ist kein verfügbares MLX-Modell konfiguriert",
            )
        metrics.set_model(
            model=model, role=request.role,
            alias=role.get("alias"), backend=role.get("backend"),
            local=True,
        )

        # Reload after a possible switch, while still holding the runtime lock.
        try:
            port = int(self.load_config().get("PORT", 8000))
        except Exception as exc:
            raise ProviderError("configuration_error", str(exc)) from exc
        _check_cancelled(context)
        payload = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        upstream_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        setup_ms = round((time.monotonic() - setup_started) * 1000, 2)
        inference_started = time.monotonic()
        result = self._request_json(upstream_request, metrics)
        inference_ms = round((time.monotonic() - inference_started) * 1000, 2)
        _check_cancelled(context)
        try:
            choice = result["choices"][0]
            message = choice["message"]
            content = message.get("content")
            reasoning = message.get("reasoning")
            if content is not None and not isinstance(content, str):
                raise ValueError("content must be text")
            if reasoning is not None and not isinstance(reasoning, str):
                raise ValueError("reasoning must be text")
            output = (content or reasoning or "").strip()
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not isinstance(finish_reason, str):
                raise ValueError("finish_reason must be text")
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderError("invalid_response", "Ungültige Agent-LLM-Antwort") from exc

        completed = metrics.finish(
            usage=result.get("usage"), output_text=output, finish_reason=finish_reason,
        )
        return ModelResponse(
            text=output, model=model, role=request.role,
            usage=dict(completed["usage"]), finish_reason=finish_reason,
            telemetry={"queue_wait_ms": completed["timings_ms"].get("queue_wait"),
                       "model_setup_ms": setup_ms, "upstream_request_ms": inference_ms,
                       "usage_method": completed["usage"].get("count_method")},
        )

    @staticmethod
    def _request_json(request, metrics):
        try:
            connect_started = time.monotonic()
            with urllib.request.urlopen(request, timeout=900) as response:
                metrics.set_upstream_connect((time.monotonic() - connect_started) * 1000)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ProviderError("http_error", f"Agent-LLM HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            code = "timeout" if isinstance(exc.reason, TimeoutError) else "unavailable"
            raise ProviderError(code, f"Agent-LLM nicht erreichbar: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError("timeout", f"Agent-LLM Zeitlimit überschritten: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("invalid_response", "Ungültige Agent-LLM-Antwort") from exc
        except ConnectionError as exc:
            raise ProviderError("unavailable", f"Agent-LLM nicht erreichbar: {exc}") from exc
