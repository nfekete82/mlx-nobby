"""Offline capability checks and rejection before any queue/runtime side effects."""
import os
import plistlib
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

import video_profiles
import video_registry
import video_service
from agent import app as agent
from agent import media_queue


@pytest.mark.parametrize('options', [None, {}, {'profile': 'standard'}])
def test_normal_agent_request_defaults_to_standard(options):
    with mock.patch.object(agent, 'compile_video_prompt', side_effect=lambda value: value):
        request = agent.ChatActionRequest(prompt='Erstelle ein Video von einem Hund im Park', video_options=options)
        payload = agent._video_payload(request, 't2v')
    assert video_service.VideoPayload(**payload).profile == 'standard'


@pytest.mark.parametrize('configured', ['', '/missing/adapter.safetensors'])
def test_unavailable_rejected_before_native_job_start(configured):
    with mock.patch.dict(os.environ, {'LTX_MLX_UNCENSORED_LORA': configured}), \
         mock.patch.object(video_service.registry, 'get_model', return_value=video_registry.builtin_mlx_model()), \
         mock.patch.object(video_service, '_persist') as persist, \
         mock.patch.object(video_service.threading, 'Thread') as thread:
        request = video_service.JobCreate(operation='t2v', payload={'prompt': 'A red ball', 'profile': 'uncensored'},
                                          chat_id='test', chat_revision=0)
        assert not video_profiles.profile_capabilities(video_registry.builtin_mlx_model())['uncensored_available']
        with pytest.raises(HTTPException) as error:
            video_service.create_job(request)
        assert error.value.status_code == 422
        assert error.value.detail['code'] == 'video_profile_unavailable'
        persist.assert_not_called()
        thread.assert_not_called()


def test_readable_fixture_accepted_without_loading_weights():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = Path(tmp) / 'fixture.safetensors'
        adapter.write_bytes(b'offline fixture; no actual weights')
        with mock.patch.dict(os.environ, {'LTX_MLX_UNCENSORED_LORA': str(adapter),
                                          'LTX_MLX_UNCENSORED_LORA_STRENGTH': '1'}), \
             mock.patch.object(video_profiles, 'prepare_uncensored_loras') as load:
            assert video_profiles.profile_capabilities(video_registry.builtin_mlx_model())['uncensored_available']
            video_profiles.preflight_profile('uncensored', video_registry.builtin_mlx_model())
            load.assert_not_called()


@pytest.mark.parametrize('model', [video_registry.builtin_model(), video_registry.builtin_mlx_model()])
def test_standard_needs_no_adapter(model):
    with mock.patch.dict(os.environ, {'LTX_MLX_UNCENSORED_LORA': ''}), \
         mock.patch.object(video_profiles, 'request_loras') as check:
        video_profiles.preflight_profile('standard', model)
        check.assert_not_called()


def test_uncensored_queue_preflight_preserves_controlled_error_and_creates_no_job():
    detail = {'code': 'video_profile_unavailable', 'message': 'Uncensored unavailable'}
    with mock.patch.object(media_queue, '_service_request', side_effect=media_queue.ServiceError(422, detail)) as request, \
         mock.patch.object(media_queue, '_persist_locked') as persist, \
         mock.patch.object(media_queue, 'ensure_worker') as start:
        with pytest.raises(HTTPException) as error:
            media_queue.enqueue('video', {'payload': {'profile': 'uncensored'}})
        assert error.value.detail == detail
        request.assert_called_once_with('video', 'POST', '/preflight', {'payload': {'profile': 'uncensored'}})
        persist.assert_not_called()
        start.assert_not_called()


def test_launchd_reinstall_preserves_adapter_and_explicit_empty_disables():
    source = Path('scripts/install-launchd.sh').read_text()
    script = source.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        rendered = Path(tmp) / 'rendered.plist'
        previous = Path(tmp) / 'previous.plist'
        previous.write_bytes(plistlib.dumps({'EnvironmentVariables': {
            'LTX_MLX_UNCENSORED_LORA': '/local/a&b.safetensors',
            'LTX_MLX_UNCENSORED_LORA_STRENGTH': '0.8'}}))
        for environment, expected in [({}, '/local/a&b.safetensors'), ({'LTX_MLX_UNCENSORED_LORA': ''}, '')]:
            rendered.write_bytes(Path('launchd/templates/de.nobby.mlx-video.plist.template').read_bytes())
            with mock.patch.dict(os.environ, environment, clear=True), \
                 mock.patch('sys.argv', ['renderer', str(rendered), str(previous)]):
                exec(compile(script, 'installer', 'exec'), {})
            values = plistlib.loads(rendered.read_bytes())['EnvironmentVariables']
            assert values['LTX_MLX_UNCENSORED_LORA'] == expected
            assert values['LTX_MLX_UNCENSORED_LORA_STRENGTH'] == '0.8'


def test_chat_shows_friendly_preflight_message_with_optional_technical_details():
    detail = {'code': 'video_profile_unavailable', 'message': 'Uncensored is not configured',
              'technical_detail': 'LTX_MLX_UNCENSORED_LORA missing'}
    with mock.patch.object(agent, '_start_chat_video_job', side_effect=HTTPException(422, detail)):
        result = agent.run_chat_action(agent.ChatActionRequest(
            prompt='Create a video of a red ball', resolved_target='video', video_options={'profile': 'uncensored'}))
    assert result['status'] == 'failed'
    assert result['error'] == detail['message']
    assert result['data']['profile_availability'] == detail
