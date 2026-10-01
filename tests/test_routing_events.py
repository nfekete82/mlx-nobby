import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend import routing_observatory as obs
from backend import media_routing_ui as media


@pytest.fixture(autouse=True)
def clear_buffer():
    obs.clear_events()
    yield
    obs.clear_events()


def client_for(result=None, stream=None):
    app = FastAPI()
    obs.install_routes(app)
    app.add_middleware(obs.RoutingObservationMiddleware)

    async def endpoint(request: Request):
        await request.json()
        if stream is not None:
            async def chunks():
                for byte in stream.encode():
                    yield bytes([byte])
            return StreamingResponse(chunks(), media_type='text/event-stream')
        return result or {'tool': 'normal_chat', 'status': 'not_applicable',
                          'data': {'routing': {'intent': 'normal_chat', 'method': 'deterministic_direct', 'confidence': 1}}}
    for path in obs.PATHS:
        app.add_api_route(path, endpoint, methods=['POST'])
    return TestClient(app)


def test_chat_event_and_metrics_across_arbitrary_chunks():
    metrics = {'calls': [{'trace_id': 'trace123456', 'status': 'completed',
                         'model': {'role': 'chat', 'alias': 'qwen38'},
                         'timings_ms': {'queue_wait': 12, 'ttft': 19}}]}
    stream = 'event: metrics\ndata: ' + json.dumps(metrics) + '\n\n'
    stream += 'data: {"type":"reasoning","text":"private reasoning"}\n\n'
    stream += 'data: {"type":"content","text":"hello"}\n\n'
    stream += 'event: done\ndata: {}\n\n'
    client = client_for(stream=stream)
    response = client.post('/api/chat/reliable-stream', json={'messages': [{'role': 'user', 'content': 'PrivateName secret@email.test'}]})
    assert response.text == stream
    event = obs.events()[0]
    assert event['source'] == 'chat' and event['selected_route'] == 'chat'
    assert event['model'] == 'qwen38' and event['selected_model_role'] == 'chat'
    assert event['latency_ms']['runtime_wait'] == 12
    assert event['latency_ms']['first_semantic_output'] is not None
    assert event['latency_ms']['routing'] is None
    assert event['request_id'] == 'trace123456' and event['success'] is True
    assert 'PrivateName' not in json.dumps(event) and 'private reasoning' not in json.dumps(event)


def test_vision_event_records_attachment_context_without_content():
    client = client_for(stream='data: {"type":"content","text":"a cat"}\n\n')
    client.post('/api/chat/stream', json={'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Describe this'}, {'type': 'image_url', 'image_url': {'url': 'data:SECRET'}}]}]})
    event = obs.events()[0]
    assert event['source'] == 'vision' and event['selected_route'] == 'chat'
    assert event['vision'] and event['attachment_types'] == ['image']
    assert event['attachment_count'] == 1 and 'SECRET' not in json.dumps(event)


@pytest.mark.parametrize(('prompt', 'proposal', 'expected'), [
    ('Hallo', 'chat', 'chat'),
    ('Erstelle ein Bild von einer Katze', 'image', 'image'),
    ('Erstelle einen Prompt für ein Bild', 'image', 'chat'),
    ('Erstelle mir einen Prompt für LTX 2.5', 'video', 'chat'),
    ('Beschreibe dieses Bild', 'image', 'chat'),
])
def test_preflight_observes_existing_guards_without_persistence(tmp_path, monkeypatch, prompt, proposal, expected):
    store = tmp_path / 'feedback.json'
    monkeypatch.setattr(media, 'ROUTING_OBSERVATORY_FILE', store)
    payload = {'prompt': prompt, 'file_context': {'kind': 'image'}}
    response = json.loads(media.guard_media_route_payload(json.dumps(payload).encode(),
                          json.dumps({'target': proposal}).encode(), record=True, duration_ms=5))
    event = obs.events()[0]
    assert response['target'] == expected == event['selected_route']
    assert event['phase'] == 'preflight' and event['attachment_count'] == 1
    assert event['latency_ms']['routing'] == 5
    assert event['prompt_length'] == len(prompt)
    assert prompt not in json.dumps(event)
    assert not store.exists()


def test_actual_dispatch_route_model_and_failure():
    result = {'tool': 'image_generate', 'status': 'queued', 'data': {
        'job': {'payload': {'model': 'juggernaut'}},
        'routing': {'intent': 'image_generate', 'method': 'central_media_intent'}}}
    client = client_for(result=result)
    client.post('/api/mlx/chat/actions', json={'prompt': 'Erstelle ein Bild einer Katze'})
    event = obs.events()[0]
    assert event['selected_route'] == 'image' and event['source'] == 'image'
    assert event['phase'] == 'dispatch'
    assert event['selected_model_role'] == 'image' and event['model'] == 'juggernaut'
    client = client_for(result={'tool': 'image_generate', 'status': 'failed', 'error': 'Private error'})
    client.post('/api/mlx/chat/actions', json={'prompt': 'Generate an image'})
    assert obs.events()[0]['success'] is False
    assert 'Private error' not in json.dumps(obs.events())


def test_fallback_and_agent():
    client = client_for(result={'tool': 'normal_chat', 'data': {'routing': {
        'intent': 'normal_chat', 'method': 'safe_fallback', 'reason': 'secret prompt echo'}}})
    client.post('/api/mlx/chat/actions', json={'prompt': 'hello'})
    assert obs.events()[0]['fallback'] is True
    assert 'secret prompt echo' not in json.dumps(obs.events())
    client_for().post('/api/mlx/agent/run', json={'goal': 'Analyse system'})
    assert obs.events()[0]['source'] == 'agent'


def test_ring_buffer_concurrent_filter_stats_clear_api():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: obs.record_event(source='chat', route='chat', role='chat',
                      success=i % 2 == 0, fallback=i % 2 != 0, routing_ms=i), range(600)))
    assert len(obs.events(limit=9999)) == 500
    client = client_for()
    response = client.get('/api/routing/events?route=chat&source=chat&model_role=chat&success=false&fallback=true&limit=3')
    assert response.status_code == 200 and len(response.json()['events']) == 3
    assert all(not e['success'] and e['fallback'] for e in response.json()['events'])
    assert client.get('/api/routing/events?route=image').json()['events'] == []
    summary = client.get('/api/routing/stats').json()
    retained = obs.events(limit=500)
    expected = sum(e['fallback'] for e in retained) / len(retained)
    assert summary['total_events'] == 500 and summary['fallback_rate'] == expected
    assert summary['error_rate'] == expected and summary['routing_p95_ms'] >= summary['routing_p50_ms']
    client.delete('/api/routing/events')
    assert obs.events() == []


def test_feedback_only_persists_on_submission(tmp_path, monkeypatch):
    store = tmp_path / 'feedback.json'
    monkeypatch.setattr(media, 'ROUTING_OBSERVATORY_FILE', store)
    event = obs.record_event(prompt='secret prompt', route='chat', success=True)
    assert not store.exists()
    media.save_routing_feedback(event['id'], True)
    assert store.exists() and 'secret prompt' not in store.read_text()
    assert obs.events()[0]['feedback']['correct'] is True


def test_observer_does_not_delay_stream_delivery():
    delivered = []
    async def app(scope, receive, send):
        await receive()
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-type', b'text/event-stream')]})
        await send({'type': 'http.response.body', 'body': b'data: {"type":"content","text":"hi"}\n\n', 'more_body': True})
        assert len(delivered) == 2
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
    async def receive():
        return {'type': 'http.request', 'body': b'{"messages":[]}', 'more_body': False}
    async def send(message):
        delivered.append(message)
    asyncio.run(obs.RoutingObservationMiddleware(app)(
        {'type': 'http', 'method': 'POST', 'path': '/api/chat/stream'}, receive, send))
    assert len(obs.events()) == 1


def test_runtime_recovery_is_correlated_without_new_sse_events(monkeypatch):
    from backend import chat_reliability_routes as reliable
    monkeypatch.setattr(reliable, '_json_request', lambda *a, **kw: {'scheduled': True})
    async def app(scope, receive, send):
        await receive()
        # asyncio.to_thread propagates the existing observation context.
        await asyncio.to_thread(reliable._request_recovery, 'http://agent', 'chat_first_byte_timeout')
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})
    async def receive():
        return {'type': 'http.request', 'body': b'{"messages":[]}'}
    async def send(message):
        pass
    asyncio.run(obs.RoutingObservationMiddleware(app)(
        {'type': 'http', 'method': 'POST', 'path': '/api/chat/reliable-stream'}, receive, send))
    event = obs.events()[0]
    assert event['fallback'] and event['fallback_reason'] == 'runtime_recovery'


def test_existing_job_reads_enrich_dispatch_without_new_events():
    app = FastAPI()
    app.add_middleware(obs.RoutingObservationMiddleware)
    @app.get('/api/mlx/image-jobs/job123')
    def progress():
        return {'id': 'job123', 'operation': 'generate', 'status': 'completed',
                'model': 'juggernaut', 'started_at': 101, 'created_at': 100,
                'finished_at': 105, 'result': {}}
    event = obs.record_event(source='image', route='image', phase='dispatch')
    obs.update_event(event['id'], job_id='job123', timestamp=100)
    response = TestClient(app).get('/api/mlx/image-jobs/job123')
    assert response.status_code == 200 and len(obs.events()) == 1
    event = obs.events()[0]
    assert event['model'] == 'juggernaut' and event['selected_model_role'] == 'image'
    assert event['phase'] == 'execution' and event['success'] is True
    assert event['latency_ms']['runtime_wait'] == 1000 and event['latency_ms']['total'] == 5000


def test_vision_fallback_records_actual_role_even_without_metrics():
    async def app(scope, receive, send):
        await receive()
        obs.observe_vision_selection({'role': 'vision', 'runtime': {
            'resolved': {'repo': '/private/models/vision-model', 'alias': 'vision-safe'}}})
        await send({'type': 'http.response.start', 'status': 503, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})
    async def receive():
        return {'type': 'http.request', 'body': b'{"messages":[]}'}
    async def send(message):
        pass
    asyncio.run(obs.RoutingObservationMiddleware(app)(
        {'type': 'http', 'method': 'POST', 'path': '/api/chat/stream'}, receive, send))
    event = obs.events()[0]
    assert event['fallback'] and event['fallback_reason'] == 'vision_role_fallback'
    assert event['selected_model_role'] == 'vision' and event['model'] == 'vision-safe'
    assert event['success'] is False and event['error_code'] == 'http_503'
    assert '/private/models' not in json.dumps(event)
