"""Benchmark telemetry must distinguish transport heartbeats from model output."""
import importlib.util
import io
import json
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'benchmark_chat', Path(__file__).resolve().parents[1] / 'scripts/benchmark-chat.py'
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def measured(body, native=False):
    payload = {'trace_id': 'test', 'messages': []}
    if native:
        payload['stream'] = False
    with mock.patch.object(benchmark.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
        return benchmark.measure('http://127.0.0.1:8090/test', payload)


def test_heartbeat_is_transport_only_and_multiline_sse_preserves_metrics():
    row = measured(
        b': vision request pending\n\n'
        b'event: sources\ndata: {"sources":[]}\n\n'
        b'data: {"type":"reasoning",\ndata: "text":"Think"}\n\n'
        b'data: {"type":"content","text":"Answer"}\n\n'
        b'event: metrics\ndata: {"calls":[{"usage":{"output_tokens":3}}]}\n\n'
        b'event: done\ndata: {}\n\n'
    )
    assert len(row['heartbeats_s']) == 1
    assert row['first_semantic_s'] > row['first_transport_s']
    assert row['output'] == 'ThinkAnswer'
    assert row['metrics'][0]['calls'][0]['usage']['output_tokens'] == 3
    assert row['errors'] == []


def test_empty_stream_and_explicit_error_are_not_successes():
    row = measured(b': pending\n\nevent: done\ndata: {}\n\n')
    assert row['first_semantic_s'] is None
    assert row['errors'] == ['No semantic output']
    row = measured(b'event: error\ndata: {"error":"runtime unavailable"}\n\n')
    assert row['errors'] == ['runtime unavailable']


def test_non_streaming_native_timing_is_not_reported_as_ttft():
    body = {'choices': [{'message': {'content': 'red and blue'}}],
            'timings': {'prompt_ms': 123, 'predicted_per_second': 30},
            'usage': {'completion_tokens': 3}}
    row = measured(json.dumps(body).encode(), native=True)
    assert row['first_semantic_s'] is None
    assert row['native_response']['timings']['prompt_ms'] == 123
    assert row['output'] == 'red and blue'
    assert row['errors'] == []


def test_transport_failure_is_retained_in_results():
    with mock.patch.object(benchmark.urllib.request, 'urlopen', side_effect=TimeoutError('late')):
        row = benchmark.measure('http://127.0.0.1:8090/test', {'trace_id': 'test'})
    assert row['first_semantic_s'] is None
    assert row['errors'] == ['late']
    assert row['total_s'] >= 0
