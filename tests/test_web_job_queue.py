"""Queue/cancel acceptance through the production Web app and Agent contract."""
import io
import json
import threading
import urllib.error
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import media_queue, service_proxy, shorts_drafts, shorts_jobs
from agent.shorts_planner import ShortProject
from backend import app as web_backend
from backend.entrypoint import app as production_app
from backend.system_health_routes import install_routes

JOB_ID = 'a' * 24


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(media_queue, 'QUEUE_DIRECTORY', tmp_path / 'queue')
    monkeypatch.setattr(media_queue, 'QUEUE_FILE', tmp_path / 'queue/jobs.json')
    monkeypatch.setattr(media_queue, 'SHORTS_FILE', tmp_path / 'shorts/jobs.json')
    monkeypatch.setattr(media_queue, 'ensure_worker', lambda: None)
    monkeypatch.setattr(media_queue, '_next_job_id', lambda: None)
    monkeypatch.setattr(media_queue, '_jobs', {})
    monkeypatch.setattr(media_queue, '_loaded', False)
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path / 'shorts')
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'shorts/jobs.json')
    monkeypatch.setattr(media_queue, '_service_request', lambda *args, **kw: (_ for _ in ()).throw(
        media_queue.ServiceError(404, 'Job not found')))
    monkeypatch.setattr(web_backend, 'AGENT_URL', 'http://127.0.0.1:8010')
    agent = FastAPI()
    service_proxy.install_routes(agent, lambda: 8000, threading.RLock())
    agent_client = TestClient(agent)
    calls = []

    def urlopen(request, timeout):
        parsed = urllib.parse.urlsplit(request.full_url)
        assert parsed.netloc == '127.0.0.1:8010'
        path = parsed.path + ('?' + parsed.query if parsed.query else '')
        calls.append((request.method, path, request.data, timeout))
        response = agent_client.request(request.method, path, content=request.data)
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code,
                                         'Agent response', {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    monkeypatch.setattr(web_backend.urllib.request, 'urlopen', urlopen)
    return TestClient(production_app, base_url='http://localhost'), calls, tmp_path


def project():
    return ShortProject.model_validate({
        'schema_version': 2, 'title': 'Cancellation fixture', 'duration': 5,
        'voice_enabled': False, 'music_enabled': False,
        'scenes': [{'id': 'scene-1', 'duration': 5, 'video_prompt': 'A neutral scene'}],
    })


def test_production_entrypoint_installs_queue_routes_once(bridge):
    client, calls, _ = bridge
    paths = [(r.path, r.methods) for r in production_app.routes if 'job-queue' in getattr(r, 'path', '')]
    assert paths == [('/api/system/job-queue', {'GET'}),
                     ('/api/system/job-queue/{kind}/{job_id}/cancel', {'POST'})]
    app = FastAPI()
    install_routes(app, lambda *args, **kw: {})
    count = len(app.routes)
    install_routes(app, lambda *args, **kw: {})
    assert len(app.routes) == count
    image = media_queue.enqueue('image', {'payload': {'prompt': 'Temporary queue fixture'}, 'chat_id': 'test'})
    response = client.get('/api/system/job-queue?limit=1')
    assert response.status_code == 200
    body = response.json()
    assert body['jobs'][0]['id'] == image['id']
    assert body['jobs'][0]['kind'] == 'image'
    assert body['jobs'][0]['cancellable'] is True
    assert body['waiting_count'] == 1
    assert body['persistent'] is True
    assert 'request' not in body['jobs'][0]
    assert calls[-1] == ('GET', '/api/system/job-queue?limit=1', None, 20)
    client.get('/api/system/job-queue')
    assert calls[-1][1].endswith('limit=40')


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_cancel_queued_media_delegates_without_new_jobs(bridge, kind):
    client, calls, _ = bridge
    job = media_queue.enqueue(kind, {'payload': {'prompt': 'Fixture'}, 'chat_id': 'test'})
    response = client.post(f'/api/system/job-queue/{kind}/{job["id"]}/cancel')
    assert response.status_code == 200
    assert response.json()['job']['status'] == 'cancelled'
    assert response.json()['kind'] == kind
    assert calls[-1] == ('POST', f'/api/system/job-queue/{kind}/{job["id"]}/cancel', b'{}', 70)
    assert media_queue.get_job(kind, job['id'])['cancellable'] is False
    assert len(media_queue._jobs) == 1
    assert client.post(f'/api/system/job-queue/{kind}/{job["id"]}/cancel').status_code == 409


def test_shorts_cancel_keeps_draft_media_and_stops_worker(bridge, monkeypatch):
    client, calls, root = bridge
    plan = project()
    plan = plan.model_copy(update={
        'duration': 10, 'scenes': [plan.scenes[0], plan.scenes[0].model_copy(update={'id': 'scene-2'})]
    })
    draft = shorts_drafts.save_draft(plan.model_dump(mode='json'))
    job = shorts_jobs.create_short_job(plan, chat_id='fixture')
    media = root / 'retained.mp4'
    media.write_bytes(b'completed-media-fixture')
    child = 'b' * 24
    shorts_jobs._update_job(job['id'], status='running', active_video_job_id=child,
                           scene_results=[{'scene_id': 'scene-1', 'status': 'completed', 'path': str(media)}])
    child_calls = []
    entered, released = threading.Event(), threading.Event()
    def native_fixture(method, path, *args, **kwargs):
        child_calls.append((method, path))
        if method == 'GET':
            entered.set()
            assert released.wait(3)
        else:
            assert path == f'/jobs/{child}/cancel'
            released.set()
        return {'id': child, 'status': 'cancelled' if released.is_set() else 'running'}
    monkeypatch.setattr(shorts_jobs.video_api, 'request', native_fixture)
    # Run the real cooperative worker, replacing only native video transport.
    shorts_jobs.start_short_job(job['id'], request_fn=native_fixture, poll_interval=0.01)
    assert entered.wait(3)
    with shorts_jobs._workers_lock:
        thread = shorts_jobs._workers[job['id']]
    try:
        response = client.post(f'/api/system/job-queue/shorts/{job["id"]}/cancel')
        assert response.status_code == 200
        assert response.json()['job']['status'] == 'cancelled'
        assert ('POST', f'/jobs/{child}/cancel') in child_calls
    finally:
        released.set()
        thread.join(3)
    assert not thread.is_alive()
    assert job['id'] not in shorts_jobs._workers
    assert shorts_jobs.get_short_job(job['id'])['active_video_job_id'] is None
    assert media.read_bytes() == b'completed-media-fixture'
    assert shorts_drafts.get_draft(draft['id']) == draft
    assert list(shorts_jobs._load_jobs()) == [job['id']]
    queue = client.get('/api/system/job-queue').json()
    item = next(j for j in queue['jobs'] if j['id'] == job['id'])
    assert item['status'] == 'cancelled' and not item['cancellable']
    assert client.post(f'/api/system/job-queue/shorts/{job["id"]}/cancel').status_code == 409


@pytest.mark.parametrize('kind', ['image', 'video', 'shorts'])
def test_unknown_jobs_return_404(bridge, kind):
    client, _, _ = bridge
    assert client.post(f'/api/system/job-queue/{kind}/{JOB_ID}/cancel').status_code == 404


@pytest.mark.parametrize('kind,job_id', [('unsupported', JOB_ID), ('shorts', 'bad-id'), ('image', 'bad-id')])
def test_agent_authoritatively_validates_kind_and_id(bridge, kind, job_id):
    client, calls, _ = bridge
    response = client.post(f'/api/system/job-queue/{kind}/{job_id}/cancel')
    assert response.status_code == 422
    assert calls[-1][1] == f'/api/system/job-queue/{kind}/{job_id}/cancel'


def test_completed_shorts_are_not_cancellable(bridge):
    client, _, _ = bridge
    job = shorts_jobs.create_short_job(project(), chat_id='fixture')
    shorts_jobs._update_job(job['id'], status='completed')
    assert client.post(f'/api/system/job-queue/shorts/{job["id"]}/cancel').status_code == 409


@pytest.mark.parametrize('path', ['/api/system/job-queue', f'/api/system/job-queue/shorts/{JOB_ID}/cancel'])
def test_offline_agent_returns_safe_503(bridge, monkeypatch, path):
    client, _, _ = bridge
    def offline(*args, **kwargs):
        raise urllib.error.URLError('Traceback private-path secret-token')
    monkeypatch.setattr(web_backend.urllib.request, 'urlopen', offline)
    response = client.request('POST' if path.endswith('/cancel') else 'GET', path)
    assert response.status_code == 503
    assert 'private-path' not in response.text and 'secret-token' not in response.text


def test_upstream_failure_is_sanitized_and_status_preserved(bridge, monkeypatch):
    client, _, _ = bridge
    def failure(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 500, 'error', {},
                                     io.BytesIO(b'{"detail":"Traceback private-path secret-token"}'))
    monkeypatch.setattr(web_backend.urllib.request, 'urlopen', failure)
    response = client.get('/api/system/job-queue')
    assert response.status_code == 500
    assert response.json() == {'detail': 'Queue-Anfrage fehlgeschlagen'}


def test_methods_queries_guards_and_path_encoding(bridge):
    client, calls, _ = bridge
    assert client.get('/api/system/job-queue?limit=not-an-int').status_code == 422
    assert calls == []
    assert client.post('/api/system/job-queue').status_code == 405
    assert client.get(f'/api/system/job-queue/shorts/{JOB_ID}/cancel').status_code == 405
    assert client.get('/api/system/job-queue', headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.get('/api/system/job-queue', headers={'Host': 'example.com'}).status_code == 403
    assert calls == []
    client.post(f'/api/system/job-queue/bad%3Fkind/{JOB_ID}/cancel')
    assert calls[-1][1] == f'/api/system/job-queue/bad%3Fkind/{JOB_ID}/cancel'
    assert client.post(f'/api/system/job-queue/shorts/..%2F{JOB_ID}/cancel').status_code == 404
