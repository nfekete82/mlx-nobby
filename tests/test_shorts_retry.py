"""Retries resume the missing phase with validated, persisted artifacts."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import image_api, shorts_jobs, shorts_studio, shorts_drafts, shorts_draft_routes
from agent import shorts_consistency_runtime as runtime
from agent.shorts_planner import ShortProject
from agent.shorts_studio_routes import list_short_history


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path / 'shorts')
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'shorts/jobs.json')
    monkeypatch.setattr(shorts_jobs, 'MUSIC_DIRECTORY', tmp_path / 'music')
    monkeypatch.setattr(shorts_jobs, 'start_short_job', Mock())
    monkeypatch.setattr(image_api, 'request', Mock(side_effect=AssertionError('Image service must not be used')))
    original = runtime._ORIGINAL_RUN_SHORT_JOB or shorts_jobs.run_short_job
    monkeypatch.setattr(runtime, '_ORIGINAL_RUN_SHORT_JOB', original)
    return tmp_path


def project(**changes):
    data = dict(schema_version=2, title='Retry', duration=10, voice_enabled=True,
                music_enabled=False, subtitles_enabled=False, consistency_mode=True,
                scenes=[dict(id=f'scene-{i}', duration=5, narration='Hello', video_prompt='Office') for i in range(2)])
    data.update(changes)
    return ShortProject.model_validate(data)


def artifact(root, name):
    path = root / name
    path.write_bytes(b'nonempty-fixture')
    return str(path)


def failed_job(root, *, compose=False, value=None, keyframes=None):
    job = shorts_jobs.create_short_job(value or project(), chat_id='test')
    return shorts_jobs._update_job(job['id'], status='failed', phase='failed', current_scene=2,
        keyframe_results=keyframes or [],
        error='Traceback: /private/secret INTERNAL', tts_status='completed' if compose else 'failed',
        tts_path=artifact(root, 'tts.mp3') if compose else None,
        scene_results=[dict(scene_id=f'scene-{i}', status='completed', path=artifact(root, f'{i}.mp4')) for i in range(2)])


def compose(command, **kwargs):
    Path(command[-1]).write_bytes(b'final-fixture')


@pytest.mark.parametrize('compose_failed', [False, True])
def test_retry_full_videos_skips_image_and_ltx_and_reuses_complete_tts(store, monkeypatch, compose_failed):
    source = failed_job(store, compose=compose_failed)
    tts = Mock(return_value=b'audio-fixture')
    monkeypatch.setattr('agent.shorts_composer.scene_tts', tts)
    video = Mock(side_effect=AssertionError('LTX must not be used'))
    revision = shorts_studio.retry_short_job(source['id'])
    result = runtime.run_consistent_short_job(revision['id'], request_fn=video, compose_fn=compose,
                                              tts_request_fn=Mock(), poll_interval=0)
    assert result['status'] == 'completed'
    assert result['scene_results'] == source['scene_results']
    assert result['tts_path'] == source['tts_path'] if compose_failed else result['tts_path'] != source['tts_path']
    assert tts.call_count == (0 if compose_failed else 1)
    image_api.request.assert_not_called()
    video.assert_not_called()
    assert shorts_jobs.get_short_job(source['id']) == source


@pytest.mark.parametrize('invalid', ['missing', 'empty', 'directory'])
def test_invalid_video_renders_only_missing_scene_from_valid_keyframe(store, monkeypatch, invalid):
    source = failed_job(store, keyframes=[dict(scene_id='scene-1', status='completed', path=artifact(store, 'frame.png'))])
    bad = Path(source['scene_results'][1]['path'])
    bad.unlink()
    if invalid == 'empty': bad.touch()
    if invalid == 'directory': bad.mkdir()
    monkeypatch.setattr('agent.shorts_composer.scene_tts', Mock(return_value=b'audio-fixture'))
    calls = []
    def video(method, path, payload=None, **kwargs):
        calls.append((method, payload))
        return {'id': 'a' * 24} if method == 'POST' else {'status': 'completed', 'result': {'path': artifact(store, 'new.mp4')}}
    revision = shorts_studio.retry_short_job(source['id'])
    assert len(revision['scene_results']) == 1
    result = runtime.run_consistent_short_job(revision['id'], request_fn=video, compose_fn=compose,
                                              tts_request_fn=Mock(), poll_interval=0)
    assert result['status'] == 'completed'
    assert [method for method, _ in calls] == ['POST', 'GET']
    assert calls[0][1]['operation'] == 'i2v'
    assert calls[0][1]['payload']['first_frame'] == source['keyframe_results'][0]['path']
    assert result['scene_results'][0] == source['scene_results'][0]
    image_api.request.assert_not_called()


def test_missing_video_and_keyframe_still_require_preflight_before_allocating_retry(store, monkeypatch):
    source = failed_job(store)
    Path(source['scene_results'][1]['path']).unlink()
    monkeypatch.setattr(image_api, 'request', Mock(return_value={'models': []}))
    before = deepcopy(shorts_jobs._load_jobs())
    with pytest.raises(ValueError, match='Keyframe-Generator'):
        shorts_studio.retry_short_job(source['id'])
    assert shorts_jobs._load_jobs() == before
    shorts_jobs.start_short_job.assert_not_called()


@pytest.mark.parametrize('invalid', ['empty', 'missing', 'directory'])
def test_invalid_completed_tts_is_regenerated(store, monkeypatch, invalid):
    source = failed_job(store, compose=True)
    path = Path(source['tts_path']); path.unlink()
    if invalid == 'empty': path.touch()
    if invalid == 'directory': path.mkdir()
    tts = Mock(return_value=b'audio-fixture')
    monkeypatch.setattr('agent.shorts_composer.scene_tts', tts)
    revision = shorts_studio.retry_short_job(source['id'])
    result = runtime.run_consistent_short_job(revision['id'], request_fn=Mock(), compose_fn=compose, poll_interval=0)
    assert result['status'] == 'completed'
    tts.assert_called_once()
    assert result['tts_path'] != source['tts_path']


@pytest.mark.parametrize('changes', [{'voice_enabled': False}, {'scenes': [dict(id=f'scene-{i}', duration=5, narration='', video_prompt='Office') for i in range(2)]}])
def test_retry_disabled_or_empty_narration_never_requests_tts(store, monkeypatch, changes):
    source = failed_job(store, value=project(**changes))
    tts = Mock(side_effect=AssertionError('TTS must not be used'))
    monkeypatch.setattr('agent.shorts_composer.scene_tts', tts)
    revision = shorts_studio.retry_short_job(source['id'])
    result = runtime.run_consistent_short_job(revision['id'], request_fn=Mock(), tts_request_fn=tts,
                                              compose_fn=compose, poll_interval=0)
    assert result['status'] == 'completed' and result['tts_status'] == 'disabled'
    tts.assert_not_called()


def test_draft_revision_checks_reuse_before_preflight(store):
    source = failed_job(store)
    with shorts_jobs._jobs_lock:
        jobs = shorts_jobs._load_jobs()
        jobs[source['id']]['status'] = 'completed'
        shorts_jobs._save_jobs(jobs)
    draft = shorts_drafts.save_draft(source['project'], source_job_id=source['id'])
    revision = shorts_drafts.render_draft(draft['id'])
    assert revision['scene_results'] == source['scene_results']
    image_api.request.assert_not_called()


def test_old_persisted_job_and_v1_caption_fallback(store):
    value = ShortProject.model_validate(dict(title='Legacy', duration=5, music_enabled=False,
        scenes=[dict(id='old', duration=5, narration='Legacy narration', video_prompt='Office')]))
    assert value.schema_version == 1 and value.scenes[0].caption == 'Legacy narration'
    job = shorts_jobs.create_short_job(value, chat_id='legacy')
    with shorts_jobs._jobs_lock:
        jobs = shorts_jobs._load_jobs()
        jobs[job['id']]['status'] = 'completed'
        jobs[job['id']].pop('keyframe_results', None)
        jobs[job['id']]['future_optional_metadata'] = {'version': 3}
        shorts_jobs._save_jobs(jobs)
    draft = shorts_drafts.save_draft(value.model_dump(), source_job_id=job['id'])
    assert draft['project']['schema_version'] == 1
    assert ShortProject.model_validate(draft['project']).model_dump() == value.model_dump()
    assert list_short_history()['projects'][0]['id'] == job['id']


def test_api_planner_failure_is_safe(store, monkeypatch):
    monkeypatch.setattr(shorts_draft_routes, 'model_provider', Mock())
    monkeypatch.setattr('agent.shorts_planner.plan_short', Mock(side_effect=RuntimeError('Traceback /private/secret')))
    app = FastAPI(); shorts_draft_routes.install_routes(app)
    response = TestClient(app).post('/api/shorts/plan', json={'prompt':'Office', 'chat_id':'test'})
    assert response.status_code == 502
    assert 'Szenenplanung' in response.json()['detail']
    assert 'Traceback' not in response.text and '/private/secret' not in response.text


def test_unknown_job_failure_is_safe_in_public_job_and_history(store):
    from agent.app import _shorts_job_tool_result
    source = failed_job(store)
    public = _shorts_job_tool_result(source)
    assert 'Traceback' not in str(public) and '/private/secret' not in str(public)
    summary = list_short_history()['projects'][0]
    assert 'Traceback' not in str(summary) and '/private/secret' not in str(summary)
    assert summary['error_code'] == 'SHORTS_RENDER_FAILED'


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/plan', {'prompt':'Office','chat_id':'test'}),
    ('GET', '/capabilities', None), ('GET', '/drafts', None),
    ('POST', '/drafts', {}), ('GET', '/drafts/draft', None),
    ('PUT', '/drafts/draft', {'project':{},'expected_version':1}),
    ('DELETE', '/drafts/draft', None), ('GET', '/drafts/draft/preflight', None),
    ('POST', '/drafts/draft/plan', {}), ('POST', '/drafts/draft/render', {}),
    ('POST', '/drafts/draft/duplicate', {}),
    ('POST', '/drafts/draft/scenes/scene-1/improve', {}),
])
def test_web_draft_proxy_contract(method, path, body):
    from backend.shorts_studio_routes import install_routes
    proxy = Mock(return_value={'ok':True})
    app = FastAPI(); install_routes(app, proxy)
    response = TestClient(app).request(method, '/api/mlx/shorts'+path, json=body)
    assert response.status_code in {200, 201, 202}, response.text
    assert proxy.call_args.args[:3] == (method, '/api/shorts'+path, body)


def test_agent_scene_media_serves_valid_file_and_rejects_empty_file(store):
    job = failed_job(store)
    app = FastAPI(); shorts_draft_routes.install_routes(app)
    client = TestClient(app)
    route = f"/api/shorts/jobs/{job['id']}/scenes/scene-0/video"
    assert client.get(route).content == b'nonempty-fixture'
    Path(job['scene_results'][0]['path']).write_bytes(b'')
    assert client.get(route).status_code == 404
