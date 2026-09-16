import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from agent.model_provider import MLXProvider, ModelRequest, ModelResponse, ProviderError
from agent.run_state import RunContext, bind_run_context
from backend import observability


class TrackingLock:
    def __init__(self):
        self.held = False
        self.on_enter = None

    def __enter__(self):
        self.held = True
        if self.on_enter:
            self.on_enter()
        return self

    def __exit__(self, *args):
        self.held = False


def upstream(content=" result ", usage=None, **message_fields):
    return io.BytesIO(json.dumps({
        "choices": [{"message": {"content": content, **message_fields}, "finish_reason": "stop"}],
        "usage": usage,
    }).encode("utf-8"))


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        observability.reset_metrics()
        self.lock = TrackingLock()
        self.resolver = mock.Mock(return_value={
            "resolved": {"repo": "local/model", "alias": "local", "backend": "mlx_lm"},
        })
        self.config = mock.Mock(return_value={"PORT": "8012"})
        self.provider = MLXProvider(self.lock, self.resolver, self.config)
        self.request = ModelRequest(messages=[{"role": "user", "content": "Plan an action"}])
        self.context = RunContext("provider-run", "chat-one", None, None, ())
        self.opener = mock.patch("agent.model_provider.urllib.request.urlopen")
        self.urlopen = self.opener.start()
        self.addCleanup(self.opener.stop)
        self.urlopen.return_value = upstream()

    def test_request_defaults_match_existing_agent(self):
        self.assertEqual(self.request.role, "agent")
        self.assertEqual(self.request.max_tokens, 1200)
        self.assertEqual(self.request.temperature, 0.1)

    def test_local_request_payload_and_response(self):
        self.urlopen.return_value = upstream('{"action":"final","answer":"done"}')
        response = self.provider.complete(self.request)
        self.assertIsInstance(response, ModelResponse)
        self.assertEqual(response.text, '{"action":"final","answer":"done"}')
        self.assertEqual(response.model, "local/model")
        self.assertEqual(response.role, "agent")
        self.assertEqual(response.finish_reason, "stop")
        self.resolver.assert_called_once_with("agent")
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8012/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {
            "model": "local/model", "messages": self.request.messages,
            "temperature": 0.1, "max_tokens": 1200,
            "chat_template_kwargs": {"enable_thinking": False},
        })
        self.assertEqual(self.urlopen.call_args.kwargs, {"timeout": 900})

    def test_lock_covers_resolution_config_reload_and_response_read(self):
        events = []

        def resolve(role):
            self.assertTrue(self.lock.held)
            events.append("switch")
            return {"resolved": {"repo": "switched/model"}}

        def config():
            self.assertTrue(self.lock.held)
            self.assertEqual(events, ["switch"])
            events.append("config")
            return {"PORT": 8001}

        response = upstream()
        original_read = response.read

        def read():
            self.assertTrue(self.lock.held)
            events.append("read")
            return original_read()

        self.resolver.side_effect = resolve
        self.config.side_effect = config
        self.urlopen.return_value = response
        with mock.patch.object(response, "read", side_effect=read):
            result = self.provider.complete(self.request)
        self.assertEqual(result.model, "switched/model")
        self.assertEqual(events, ["switch", "config", "read"])
        self.assertFalse(self.lock.held)
        self.assertTrue(response.closed)

    def test_requested_role_and_generation_parameters_are_forwarded(self):
        request = ModelRequest(self.request.messages, max_tokens=2400, temperature=0.25, role="coding")
        response = self.provider.complete(request)
        self.resolver.assert_called_once_with("coding")
        self.assertEqual(response.role, "coding")
        payload = json.loads(self.urlopen.call_args.args[0].data)
        self.assertEqual(payload["max_tokens"], 2400)
        self.assertEqual(payload["temperature"], 0.25)

    def test_content_reasoning_fallback_and_empty_output_are_preserved(self):
        for content, reasoning, expected in (("text", "thought", "text"), (None, " thought ", "thought"), ("", "", "")):
            with self.subTest(content=content, reasoning=reasoning):
                self.urlopen.return_value = upstream(content, reasoning=reasoning)
                self.assertEqual(self.provider.complete(self.request).text, expected)

    def test_usage_normalization_and_observability_share_result(self):
        for usage in (
            {"prompt_tokens": 10, "completion_tokens": 4, "completion_tokens_details": {"reasoning_tokens": 2}},
            {"input_tokens": 10, "output_tokens": 4, "reasoning_tokens": 2},
        ):
            with self.subTest(usage=usage):
                observability.reset_metrics()
                self.urlopen.return_value = upstream(usage=usage)
                with observability.trace_context("provider-usage-trace"), observability.model_call_context("agent.plan"):
                    response = self.provider.complete(self.request)
                self.assertEqual(response.usage, {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14, "reasoning_tokens": 2, "count_method": "upstream"})
                snapshot = observability.trace_snapshot("provider-usage-trace")
                self.assertEqual(snapshot["model_calls_in_turn"], 1)
                metric = snapshot["calls"][0]
                self.assertEqual(metric["purpose"], "agent.plan")
                self.assertEqual(metric["usage"], response.usage)
                self.assertEqual(metric["status"], "completed")
                self.assertIsNotNone(metric["timings_ms"]["queue_wait"])
                self.assertIsNotNone(metric["timings_ms"]["upstream_connect"])

    def test_absent_usage_is_estimated(self):
        response = self.provider.complete(self.request)
        self.assertEqual(response.usage["count_method"], "estimate")
        self.assertGreater(response.usage["input_tokens"], 0)
        self.assertGreater(response.usage["output_tokens"], 0)

    def test_timeout_is_classified_without_retry_or_fallback(self):
        for error in (TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))):
            self.urlopen.reset_mock()
            self.urlopen.side_effect = error
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete(self.request)
            self.assertEqual(caught.exception.code, "timeout")
            self.assertIs(caught.exception.__cause__, error)
            self.urlopen.assert_called_once()
            self.assertFalse(self.lock.held)

    def test_unreachable_server_preserves_error_detail(self):
        self.urlopen.side_effect = urllib.error.URLError("connection refused")
        with self.assertRaisesRegex(ProviderError, "Agent-LLM nicht erreichbar: connection refused") as caught:
            self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "unavailable")

    def test_http_error_preserves_status_and_body(self):
        self.urlopen.side_effect = urllib.error.HTTPError("http://127.0.0.1", 503, "Unavailable", {}, io.BytesIO(b"model loading"))
        with self.assertRaisesRegex(ProviderError, "Agent-LLM HTTP 503: model loading") as caught:
            self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "http_error")

    def test_missing_model_prevents_http_call(self):
        self.resolver.return_value = {"resolved": {"repo": None}}
        with self.assertRaises(ProviderError) as caught:
            self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "model_unavailable")
        self.config.assert_not_called()
        self.urlopen.assert_not_called()

    def test_model_switch_failure_preserves_message(self):
        self.resolver.side_effect = RuntimeError("model unavailable")
        with self.assertRaisesRegex(ProviderError, "model unavailable") as caught:
            self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "model_unavailable")
        self.urlopen.assert_not_called()
        self.assertFalse(self.lock.held)

    def test_invalid_config_prevents_http_call(self):
        self.config.return_value = {"PORT": "invalid"}
        with self.assertRaises(ProviderError) as caught:
            self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "configuration_error")
        self.urlopen.assert_not_called()

    def test_invalid_response_shapes_and_encoding(self):
        bodies = [
            b"not JSON", b"\xff", b"null", b"[]", b"{}", b'{"choices":[]}',
            b'{"choices":[{}]}', b'{"choices":[{"message":null}]}',
            b'{"choices":[{"message":{"content":123}}]}',
            b'{"choices":[{"message":{"reasoning":[]}}]}',
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.urlopen.return_value = io.BytesIO(body)
                with self.assertRaises(ProviderError) as caught:
                    self.provider.complete(self.request)
                self.assertEqual(caught.exception.code, "invalid_response")
                self.assertFalse(self.lock.held)

    def test_provider_failure_is_recorded_once(self):
        self.urlopen.side_effect = RuntimeError("unexpected transport error")
        with observability.trace_context("provider-error-trace"):
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete(self.request)
        self.assertEqual(caught.exception.code, "provider_error")
        snapshot = observability.trace_snapshot("provider-error-trace")
        self.assertEqual(snapshot["model_calls_in_turn"], 1)
        self.assertEqual(snapshot["calls"][0]["status"], "failed")

    def test_cancellation_before_call_prevents_model_resolution(self):
        self.context.cancel()
        with self.assertRaises(ProviderError) as caught:
            self.provider.complete(self.request, run_context=self.context)
        self.assertEqual(caught.exception.code, "cancelled")
        self.resolver.assert_not_called()
        self.urlopen.assert_not_called()

    def test_cancellation_during_lock_wait_prevents_model_resolution(self):
        self.lock.on_enter = self.context.cancel
        with self.assertRaises(ProviderError) as caught:
            self.provider.complete(self.request, run_context=self.context)
        self.assertEqual(caught.exception.code, "cancelled")
        self.resolver.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(self.lock.held)

    def test_cancellation_after_model_switch_prevents_inference(self):
        def resolve(role):
            self.context.cancel()
            return {"resolved": {"repo": "local/model"}}
        self.resolver.side_effect = resolve
        with self.assertRaises(ProviderError) as caught:
            self.provider.complete(self.request, run_context=self.context)
        self.assertEqual(caught.exception.code, "cancelled")
        self.urlopen.assert_not_called()

    def test_cancellation_after_http_read_discards_response(self):
        def open_response(*args, **kwargs):
            self.context.cancel()
            return upstream()
        self.urlopen.side_effect = open_response
        with observability.trace_context("provider-cancel-trace"):
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete(self.request, run_context=self.context)
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertEqual(observability.trace_snapshot("provider-cancel-trace")["calls"][0]["error_type"], "cancelled")


class AgentProviderCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        with mock.patch.object(Path, "home", return_value=Path(directory.name)):
            from agent import app
        cls.agent = app

    def test_agent_llm_uses_provider_and_forwards_current_context(self):
        context = RunContext("facade-run", None, None, None, ())
        response = ModelResponse('{"action":"final"}', "model", "agent", {})
        provider = mock.Mock()
        provider.complete.return_value = response
        messages = [{"role": "user", "content": "Goal"}]
        with mock.patch.object(self.agent, "agent_model_provider", return_value=provider), bind_run_context(context):
            result = self.agent.agent_llm(messages, max_tokens=600, temperature=0.2)
        self.assertEqual(result, response.text)
        provider.complete.assert_called_once_with(ModelRequest(messages, 600, 0.2), run_context=context)

    def test_default_adapter_reuses_actual_role_switch_logic(self):
        resolved = {"repo": "local/model", "alias": "agent", "backend": "mlx_lm", "available": True}
        with (
            mock.patch.object(self.agent, "resolve_model_role", side_effect=[{**resolved, "requires_switch": True}, {**resolved, "requires_switch": False}]) as resolve,
            mock.patch.object(self.agent, "switch_model_runtime", return_value={"ok": True}) as switch,
            mock.patch.object(self.agent, "load_config", return_value={"PORT": 8000}),
            mock.patch.object(self.agent.urllib.request, "urlopen", return_value=upstream("plan")),
        ):
            self.assertEqual(self.agent.agent_llm([]), "plan")
        self.assertEqual(resolve.call_args_list, [mock.call("agent"), mock.call("agent")])
        switch.assert_called_once_with("agent")

    def test_compatibility_layer_propagates_provider_error(self):
        provider = mock.Mock()
        error = ProviderError("unavailable", "offline")
        provider.complete.side_effect = error
        with mock.patch.object(self.agent, "agent_model_provider", return_value=provider):
            with self.assertRaises(ProviderError) as caught:
                self.agent.agent_llm([])
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
