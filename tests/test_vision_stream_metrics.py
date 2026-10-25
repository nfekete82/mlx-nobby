"""Vision stream timing is independent from text chat telemetry."""
import io
import json
import time
from unittest import mock

from fastapi.testclient import TestClient

from agent import app as agent_app
from agent import performance_observatory_routes as performance
from backend import observability


def setup_function():
    observability.reset_metrics()


def teardown_function():
    observability.reset_metrics()


def test_first_answer_text_is_distinct_from_reasoning_and_idempotent():
    call = observability.ModelCallMetrics(
        trace_id="vision-first-content-001",
        purpose="vision.stream",
        messages=[{"role": "user", "content": "synthetic fixture"}],
    )
    call.mark_first_token()  # Thinking starts before the description.
    ttft = call.metric["timings_ms"]["ttft"]
    assert ttft is not None
    assert call.metric["timings_ms"]["first_content"] is None

    time.sleep(0.002)
    call.mark_first_content()
    first_content = call.metric["timings_ms"]["first_content"]
    assert first_content is not None
    assert first_content >= ttft
    call.mark_first_content()
    assert call.metric["timings_ms"]["first_content"] == first_content
    call.finish(usage={"completion_tokens": 4})
    assert call.metric["status"] == "completed"


def test_nonstreaming_vision_does_not_invent_first_content():
    call = observability.ModelCallMetrics(
        trace_id="nonstream-vision-content-001", purpose="chat.vision",
    )
    call.finish(usage={"completion_tokens": 5}, output_text="response")
    assert call.metric["timings_ms"]["first_content"] is None
    assert call.metric["timings_ms"]["ttft"] is None


def test_vision_stream_does_not_pollute_chat_metrics():
    chat = observability.ModelCallMetrics(
        trace_id="text-stream-metric-001", purpose="chat.stream", messages=[],
    )
    chat.mark_first_content()
    chat.finish(usage={"prompt_tokens": 5, "completion_tokens": 20})
    with observability._TRACE_LOCK:
        chat.metric["timings_ms"].update({
            "ttft": 110.0, "first_content": 120.0,
            "generation": 1000.0, "total": 1110.0,
        })

    vision = observability.ModelCallMetrics(
        trace_id="vision-stream-metric-001", purpose="vision.stream", messages=[],
    )
    vision.mark_first_content()
    vision.finish(usage={"prompt_tokens": 50, "completion_tokens": 60})
    with observability._TRACE_LOCK:
        vision.metric["timings_ms"].update({
            "ttft": 900.0, "first_content": 1200.0,
            "generation": 2000.0, "total": 2900.0,
        })

    snapshot = performance.model_performance_snapshot(limit=20)
    text = snapshot["summary"]
    image = snapshot["vision_summary"]
    assert text["ttft_ms"]["count"] == 1
    assert text["ttft_ms"]["p50"] == 110
    assert text["tokens_per_second"]["p50"] == 20
    assert image["ttft_ms"]["count"] == 1
    assert image["ttft_ms"]["p50"] == 900
    assert image["first_content_ms"]["p50"] == 1200
    assert image["tokens_per_second"]["p50"] == 30
    assert image["total_ms"]["p50"] == 2900


def test_legacy_vision_without_stream_has_no_vision_series():
    buffered = observability.ModelCallMetrics(
        trace_id="buffered-vision-001", purpose="chat.vision", messages=[],
    )
    buffered.finish(usage={"completion_tokens": 40})
    snapshot = performance.model_performance_snapshot(limit=10)
    assert snapshot["vision_summary"]["ttft_ms"]["count"] == 0
    assert snapshot["vision_summary"]["first_content_ms"]["count"] == 0
    assert snapshot["vision_summary"]["tokens_per_second"]["count"] == 0


def test_agent_vision_worker_reports_vision_purpose_and_first_content():
    upstream = io.BytesIO(
        b'data: {"choices":[{"delta":{"reasoning":"Looking"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"red and blue"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":8,"completion_tokens":4,"total_tokens":12}}\n\n'
        b'data: [DONE]\n\n'
    )
    runtime = {
        "resolved": {
            "repo": "local-test-vision-model",
            "alias": "vision",
            "backend": "mlx_vlm",
        }
    }
    client = TestClient(agent_app.app, base_url="http://localhost")
    try:
        with (
            mock.patch.object(agent_app, "ensure_model_for_role", return_value=runtime) as ensure_role,
            mock.patch.object(agent_app, "load_config", return_value={"PORT": 8000}),
            mock.patch.object(agent_app.urllib.request, "urlopen", return_value=upstream),
        ):
            response = client.post("/api/runtime/chat/stream", json={
                "messages": [{"role": "user", "content": "Synthetic vision test"}],
                "vision_role": "vision",
                "trace_id": "test-native-vision-metrics-001",
            })
        assert response.status_code == 200, response.text
        ensure_role.assert_called_once_with("vision")
        assert "red and blue" in response.text
        snapshot = observability.trace_snapshot("test-native-vision-metrics-001")
        call = snapshot["calls"][0]
        assert call["purpose"] == "vision.stream"
        assert call["timings_ms"]["ttft"] is not None
        assert call["timings_ms"]["first_content"] is not None
        assert call["timings_ms"]["first_content"] >= call["timings_ms"]["ttft"]
        assert call["usage"]["output_tokens"] == 4
    finally:
        client.close()
