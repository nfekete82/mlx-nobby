"""Synchronous agent-model contract and the existing local MLX transport."""

from dataclasses import dataclass
import json
import time
from typing import Callable, ContextManager, Protocol
import urllib.error
import urllib.request

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
    ):
        self.runtime_lock = runtime_lock
        self.ensure_model_for_role = ensure_model_for_role
        self.load_config = load_config

    def complete(self, request: ModelRequest, *, run_context: RunContext | None = None) -> ModelResponse:
        _check_cancelled(run_context)
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
            with self.runtime_lock:
                metrics.set_queue_wait((time.monotonic() - wait_started) * 1000)
                _check_cancelled(run_context)
                return self._complete(request, run_context, metrics)
        except ProviderError as exc:
            metrics.fail(exc.code)
            raise
        except Exception as exc:
            metrics.fail("provider_error")
            raise ProviderError("provider_error", str(exc)) from exc

    def _complete(self, request, context, metrics):
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
        result = self._request_json(upstream_request, metrics)
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
