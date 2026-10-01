"""Concurrent callers must take the heavy-runtime lease before the model lock."""
from contextlib import contextmanager
import io
import json
import threading
import time
from unittest import mock

import pytest
from agent import app as agent_app
from agent.model_provider import MLXProvider, ModelRequest, ProviderError
from agent.run_state import RunContext
from backend import observability


@pytest.mark.parametrize('caller', ['provider', 'image_prompt'])
def test_model_call_does_not_hold_model_lock_while_waiting_for_chat_lease(caller):
    coordinator = threading.RLock()
    model_lock = threading.RLock()
    chat_has_lease = threading.Event()
    caller_at_lease = threading.Event()
    result = {}
    errors = []

    @contextmanager
    def lease(*_args):
        caller_at_lease.set()
        with coordinator:
            yield

    def resolve(_role):
        # Role resolution re-enters the same lease in production. This
        # reproduces the former model-lock -> coordinator dependency.
        caller_at_lease.set()
        with coordinator:
            return {'resolved': {'repo': 'same/model'}}

    def chat():
        with coordinator:
            chat_has_lease.set()
            if not caller_at_lease.wait(2):
                errors.append('model caller never reached lease')
                return
            started = time.perf_counter()
            acquired = model_lock.acquire(timeout=.25)
            result['acquired'] = acquired
            result['wait_ms'] = (time.perf_counter() - started) * 1000
            if acquired:
                model_lock.release()

    def call_model():
        if not chat_has_lease.wait(2):
            errors.append('chat never acquired lease')
            return
        try:
            if caller == 'provider':
                provider = MLXProvider(model_lock, resolve, lambda: {'PORT': 8000}, runtime_lease=lease)
                result['response'] = provider.complete(ModelRequest([{'role': 'user', 'content': 'OK'}])).text
            else:
                result['response'] = agent_app.optimize_image_edit_prompt('Remove tattoos')
        except Exception as exc:
            errors.append(exc)

    body = io.BytesIO(json.dumps({'choices': [{'message': {'content': 'Remove all tattoos.'},
                                             'finish_reason': 'stop'}]}).encode())
    with (
        mock.patch('agent.model_provider._with_memory', side_effect=lambda request, context: request),
        mock.patch('agent.model_provider.urllib.request.urlopen', return_value=body),
        mock.patch.object(agent_app, 'MODEL_RUNTIME_LOCK', model_lock),
        mock.patch.object(agent_app, 'ensure_model_for_role', side_effect=resolve),
        mock.patch.object(agent_app, 'load_config', return_value={'PORT': 8000}),
        mock.patch.object(agent_app.runtime_coordinator, 'chat_runtime', side_effect=lease),
    ):
        threads = [threading.Thread(target=chat, daemon=True), threading.Thread(target=call_model, daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert result['acquired'], f"inverted locks blocked chat for {result['wait_ms']:.1f} ms"
    assert result['response'] == 'Remove all tattoos.'


def test_production_provider_injects_cancellable_runtime_lease():
    context = RunContext('lease-test', None, None, None, ())
    with mock.patch.object(agent_app.runtime_coordinator, 'chat_runtime') as lease:
        provider = agent_app.agent_model_provider()
        provider.runtime_lease(context)
    lease.assert_called_once_with(context.cancellation)


def test_cancellation_while_queued_releases_lease_without_model_resolution():
    context = RunContext('cancel-lease-test', None, None, None, ())

    @contextmanager
    def lease(_context):
        context.cancel()
        raise agent_app.runtime_coordinator.CoordinationCancelled('queued cancellation')
        yield

    resolve = mock.Mock()
    provider = MLXProvider(threading.RLock(), resolve, mock.Mock(), runtime_lease=lease)
    with observability.trace_context('cancel-lease-test'), pytest.raises(ProviderError) as error:
        provider.complete(ModelRequest([]), run_context=context)
    assert error.value.code == 'cancelled'
    resolve.assert_not_called()
    assert observability.trace_snapshot('cancel-lease-test')['calls'][0]['error_type'] == 'cancelled'
