from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent import app as agent, shorts_jobs, media_queue
from backend import app as backend


def chat(chat_id):
    return {'id': chat_id, 'title': chat_id, 'created': 1, 'updated': 2,
            'revision': 0, 'messages': [{'role': 'user', 'content': 'hello'}]}


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, 'CHAT_DIRECTORY', tmp_path / 'chats')
    monkeypatch.setattr(agent, 'IMAGE_DIRECTORY', tmp_path / 'images')
    agent.IMAGE_DIRECTORY.mkdir()
    for chat_id in ('one', 'two'):
        agent.write_chat(chat(chat_id))
    with patch.object(agent, 'cancel_chat_image_jobs_api', return_value={'cancelled_count': 2}) as images, \
         patch.object(media_queue, 'cancel_chat', return_value=[]) as videos, \
         patch.object(shorts_jobs, 'cancel_chat_jobs', return_value=[]) as shorts:
        yield TestClient(agent.app, base_url='http://localhost'), images, videos, shorts


def test_bulk_delete_cleans_history_and_chat_images_and_rejects_late_put(history):
    client, images, videos, shorts = history
    managed = '1790949737-c96699a4776b'
    owned = agent.IMAGE_DIRECTORY / f'{managed}.png'
    unrelated = agent.IMAGE_DIRECTORY / '1790949737-abcdef123456.png'
    owned.write_bytes(b'owned'); unrelated.write_bytes(b'keep')
    original = chat('one')
    original['messages'].append({'role': 'assistant', 'tool_result': {
        'artifacts': [{'image_id': managed, 'kind': 'image'}]}})
    agent.write_chat(original)
    response = client.request('DELETE', '/api/chats', json={'ids': ['one', 'two', 'local-draft']})
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['deleted_count'] == 2
    assert not owned.exists() and unrelated.exists()
    assert client.get('/api/chats').json()['chats'] == []
    assert sorted(client.get('/api/chats').json()['deleted_ids']) == ['local-draft', 'one', 'two']
    assert not list(agent.CHAT_DIRECTORY.glob('[a-z]*.json'))
    assert client.put('/api/chats/one', json=chat('one')).status_code == 410
    assert client.put('/api/chats/local-draft', json=chat('local-draft')).status_code == 410
    assert client.get('/api/chats/one').status_code == 404
    assert client.put('/api/chats/new-chat', json=chat('new-chat')).status_code == 200
    assert [item['id'] for item in client.get('/api/chats').json()['chats']] == ['new-chat']
    assert {call.args[0] for call in images.call_args_list} == {'one', 'two', 'local-draft'}
    assert {call.args for call in videos.call_args_list} == {('video', value) for value in ('one', 'two', 'local-draft')}
    assert {call.args[0] for call in shorts.call_args_list} == {'one', 'two', 'local-draft'}


def test_bulk_delete_is_atomic_when_deletion_state_cannot_be_written(history):
    client, images, _, _ = history
    with patch.object(agent.os, 'replace', side_effect=OSError('read-only')):
        response = client.delete('/api/chats')
    assert response.status_code == 500
    assert len(client.get('/api/chats').json()['chats']) == 2
    images.assert_not_called()


def test_bulk_delete_refuses_corrupt_chat_before_changing_history(history):
    client, images, _, _ = history
    agent.chat_path('bad').write_text('{')
    assert client.delete('/api/chats').status_code == 500
    assert agent.read_chat('one') and agent.read_chat('two')
    assert not agent.deleted_chat_ids()
    images.assert_not_called()


def test_invalid_ids_do_not_delete_anything(history):
    client, images, _, _ = history
    for ids in ('one', [None], ['../outside']):
        assert client.request('DELETE', '/api/chats', json={'ids': ids}).status_code == 400
    assert len(client.get('/api/chats').json()['chats']) == 2
    images.assert_not_called()


def test_tombstone_commit_keeps_history_deleted_even_if_cleanup_fails(history):
    client, _, _, _ = history
    with patch.object(agent, 'delete_chat_images', return_value=([], ['cleanup-failed'])):
        response = client.delete('/api/chats')
    assert response.status_code == 200
    assert response.json()['failed_images']
    assert client.get('/api/chats').json()['chats'] == []


def test_proxy_forwards_bulk_body_and_backend_failure():
    with patch.object(backend, 'agent_json_request', return_value={'ok': True, 'deleted_count': 2}) as proxy:
        result = backend.mlx_delete_all_chats({'ids': ['local-draft']})
        assert result['deleted_count'] == 2
        proxy.assert_called_once_with('DELETE', '/api/chats', payload={'ids': ['local-draft']}, timeout=60)


def test_shorts_cancellation_is_scoped_and_includes_unsaved_jobs():
    jobs = {'a' * 24: {'chat_id': 'one', 'status': 'running'},
            'b' * 24: {'chat_id': 'one', 'status': 'queued'},
            'c' * 24: {'chat_id': 'other', 'status': 'running'},
            'd' * 24: {'chat_id': 'one', 'status': 'completed'}}
    with patch.object(shorts_jobs, '_load_jobs', return_value=jobs), \
         patch.object(shorts_jobs, 'cancel_short_job') as cancel:
        assert shorts_jobs.cancel_chat_jobs('one') == ['a' * 24, 'b' * 24]
    assert [call.args[0] for call in cancel.call_args_list] == ['a' * 24, 'b' * 24]


def test_gallery_submission_and_bulk_delete_are_serialized(history):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from image_variants import VariantBatch

    _, images, _, _ = history
    entered, release = threading.Event(), threading.Event()
    events = []

    def submit(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        events.append('submitted')
        return {'batch': True}

    images.side_effect = lambda *args: events.append('cancelled') or {'cancelled_count': 2}
    request = VariantBatch(base_job_id='a' * 24, count=3, chat_id='one', chat_revision=0)
    with patch.object(agent.image_api, 'request', side_effect=submit), \
         patch.object(agent, '_variant_group_tool_result', side_effect=lambda value: value), \
         ThreadPoolExecutor(max_workers=2) as pool:
        pending_job = pool.submit(agent.image_variants_api, request)
        assert entered.wait(2)
        pending_delete = pool.submit(agent.delete_all_chats)
        release.set()
        assert pending_job.result(timeout=3) == {'batch': True}
        assert pending_delete.result(timeout=3)['ok']
    assert events[0] == 'submitted'
    assert 'cancelled' in events[1:]
    with patch.object(agent.image_api, 'request') as late_submit:
        with pytest.raises(agent.HTTPException) as exc:
            agent.image_variants_api(request)
        assert exc.value.status_code == 404
        late_submit.assert_not_called()


def test_shorts_planning_cannot_submit_a_job_after_bulk_delete(history):
    _, _, _, _ = history
    request = agent.ChatActionRequest(prompt='Create a short', chat_id='one', chat_revision=0)
    with patch.object(agent, 'agent_model_provider'), \
         patch.object(agent, 'plan_short', side_effect=lambda *args, **kwargs: agent.delete_all_chats() or {}), \
         patch.object(shorts_jobs, 'create_short_job') as create:
        with pytest.raises(agent.HTTPException) as exc:
            agent._start_chat_shorts_job(request)
    assert exc.value.status_code == 404
    create.assert_not_called()
