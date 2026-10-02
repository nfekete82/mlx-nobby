"""Reference routing and the actual source-bearing Edit/provider contract."""
import copy
import hashlib
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.media_intent import decide_media_intent
from agent import app as agent
import image_service as service
import image_providers


@pytest.mark.parametrize('prompt,mode', [
    ('Kannst du ein Bild erstellen, das dieser Person ähnelt?', 'resemblance'),
    ('Erstelle ein neues Bild derselben Person.', 'same_identity'),
    ('Zeige diese Person in einem modernen Büro.', 'same_identity'),
    ('Mach ein professionelles Portrait mit demselben Gesicht.', 'same_identity'),
    ('Create a new image resembling this person.', 'resemblance'),
    ('Generate another photo of the same person.', 'same_identity'),
    ('Show this person standing outside.', 'same_identity'),
    ('Keep the same face but change the setting.', 'same_identity'),
    ('Erstelle ein Bild der Frau aus dem Bild.', 'same_identity'),
    ('Make a photo similar to this person.', 'resemblance'),
])
def test_reference_intent_even_without_source(prompt, mode):
    for has_image in (True, False):
        decision = decide_media_intent(prompt, has_image=has_image)
        assert decision.intent == 'image_reference_generate'
        assert decision.target == 'image_edit'
        assert decision.reference_mode == mode


@pytest.mark.parametrize('prompt,intent', [
    ('Mach den Hintergrund blau.', 'image_edit'),
    ('Entferne die Sonnenbrille.', 'image_edit'),
    ('Entferne diese Person.', 'image_edit'),
    ('Was siehst du auf dem Bild?', 'discussion'),
    ('Welche Haarfarbe hat die Person?', 'discussion'),
    ('Sieht diese Person müde aus?', 'vision_chat'),
    ('Beschreibe das Foto.', 'discussion'),
    ('Mach aus diesem Bild ein Video.', 'video_animate'),
    ('Animiere diese Person.', 'video_animate'),
    ('Erstelle ein Bild von einem roten Sportwagen.', 'image_generate'),
    ('Erstelle einen Prompt für dieselbe Person.', 'prompt_writing'),
    ('Erstelle kein Bild derselben Person.', 'discussion'),
])
def test_other_intents_keep_priority(prompt, intent):
    assert decide_media_intent(prompt, has_image=True).intent == intent


def test_explicit_active_reference_followup_only():
    prompt = 'Jetzt draußen im Regen.'
    assert decide_media_intent(prompt, has_image=True).intent == 'vision_chat'
    decision = decide_media_intent(prompt, has_image=True, reference_context='same_identity')
    assert decision.intent == 'image_reference_generate'
    assert decision.reference_mode == 'same_identity'
    assert decide_media_intent('Erstelle ein Bild eines Autos.', has_image=True,
                               reference_context='same_identity').intent == 'image_generate'


@pytest.fixture
def runtime(tmp_path, monkeypatch, mflux_cli_contract):
    monkeypatch.setattr(service, 'OUTPUT', tmp_path)
    monkeypatch.setattr(image_providers, 'model_directory', lambda _: tmp_path)
    monkeypatch.setattr(agent, 'IMAGE_DIRECTORY', tmp_path)
    monkeypatch.setattr(service.runtime_coordinator, 'image_runtime', lambda *_: nullcontext())
    monkeypatch.setattr(agent, 'validate_chat_id', lambda _: None)
    monkeypatch.setattr(agent, 'read_chat', lambda _: {'revision': 0})
    monkeypatch.setattr(agent, 'translate_media_prompt_to_english', lambda prompt: prompt)
    monkeypatch.setattr(agent, '_image_generate_payload', lambda *_: pytest.fail('Reference degraded to T2I'))
    selected = {'id': 'local-edit', 'enabled': True, 'provider': 'mflux', 'model_family': 'qwen-image-edit',
                'base_model': 'qwen-image-edit', 'quantization': 'none', 'loras': [],
                'capabilities': ['image_edit'], 'default_steps': 8, 'default_guidance': 3.5}
    t2i = {**selected, 'id': 'juggernaut-xl', 'provider': 'sdxl', 'capabilities': ['text_to_image']}
    monkeypatch.setattr(service.registry, 'load_registry', lambda: {'models': [t2i, selected], 'default_model': t2i['id']})
    monkeypatch.setattr(service, 'availability', lambda _: (True, 'ready'))
    monkeypatch.setattr(image_providers, 'probe_mflux_cli', lambda _: {'available': True, 'supported_flags':
        frozenset('--model --prompt --width --height --steps --seed --output --image-paths --guidance'.split()), 'error': None})
    service._jobs.clear()
    source = tmp_path / 'reference.png'
    Image.new('RGB', (256, 256), 'blue').save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []
    active = [0]
    def provider(model, params, output, **kwargs):
        active[0] += 1
        assert active[0] == 1, "Reference slots must run sequentially"
        time.sleep(.002)
        assert model['id'] == 'local-edit'
        assert model['capabilities'] == ['image_edit']
        assert params['source_path'] == str(source)
        command = image_providers.mflux_command(model, params, output)
        assert command[command.index('--image-paths') + 1] == str(source)
        calls.append((copy.deepcopy(model), copy.deepcopy(params)))
        Image.new('RGB', (params['width'], params['height']), 'green').save(output)
        active[0] -= 1
    monkeypatch.setattr(service, 'run_provider', provider)
    native = TestClient(service.app, base_url='http://localhost')
    def proxy(method, path, payload=None, **kwargs):
        response = native.request(method, path, json=payload)
        if response.status_code >= 400:
            raise agent.HTTPException(response.status_code, response.json()['detail'])
        return response.json()
    monkeypatch.setattr(agent.image_api, 'request', proxy)
    yield native, TestClient(agent.app, base_url='http://localhost'), source, calls
    for job in list(service._jobs.values()):
        thread = job.get('_thread')
        if thread and thread.ident:
            thread.join(5)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    service._jobs.clear()


def wait(native, job_id):
    for _ in range(1000):
        job = native.get('/jobs/' + job_id).json()
        if job['status'] in {'completed', 'failed', 'cancelled'}:
            thread = service._jobs[job_id].get('_thread')
            if thread:
                thread.join(5)
            return native.get('/jobs/' + job_id).json()
        time.sleep(.005)
    pytest.fail('Job timed out')


def request(source, **options):
    return {'prompt': 'Erstelle ein neues Bild derselben Person im Büro.',
            'file_context': {'kind': 'image', 'stored_path': str(source), 'file_id': 'uploaded-reference'},
            'chat_id': 'reference-test', 'chat_revision': 0, 'quality': 'fast',
            'image_options': {'width': 512, 'height': 512, 'auto_size': True, 'seed': 11}, **options}


def test_attachment_to_action_to_qwen_command(runtime):
    native, client, source, calls = runtime
    payload = request(source)
    route = client.post('/api/chat/actions/route', json=payload).json()
    assert route['intent'] == 'image_reference_generate'
    response = client.post('/api/chat/actions', json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['tool'] == 'image_edit'
    completed = wait(native, result['data']['job']['id'])
    assert completed['status'] == 'completed', completed.get('error')
    artifact = client.get('/api/image/jobs/' + completed['id']).json()['artifacts'][0]
    assert artifact['semantic_operation'] == 'reference_generate'
    assert artifact['reference_used'] is True
    assert artifact['reference_mode'] == 'same_identity'
    assert artifact['reference_relation'] == 'same_identity'
    assert artifact['reference_artifact_id'] == 'uploaded-reference'
    assert artifact['provider'] == 'mflux'
    assert artifact['seed'] == 11
    assert artifact['path'] != str(source)
    assert len(calls) == 1
    assert 'Preserve the person' in calls[0][1]['prompt']
    assert 'im Büro' in calls[0][1]['prompt']
    assert '_canonical' not in client.get('/api/image/jobs/' + completed['id']).json()['data']['job']


@pytest.mark.parametrize('count', [3, 6])
def test_reference_variants_pin_source_provider_and_only_vary_seed(runtime, monkeypatch, count):
    native, client, source, calls = runtime
    result = client.post('/api/chat/actions', json=request(source)).json()
    first = wait(native, result['data']['job']['id'])
    source_job = copy.deepcopy(service._job_snapshot(service._jobs[first['id']]))
    monkeypatch.setattr(service, '_edit_model', lambda *_: pytest.fail('Re-resolved model'))
    response = native.post('/jobs/variants', json={'base_job_id': first['id'], 'count': count,
        'chat_id': 'reference-test', 'chat_revision': 0})
    assert response.status_code == 202, response.text
    group = response.json()
    for job in group['jobs']:
        completed = wait(native, job['id'])
        assert completed['operation'] == 'edit'
        assert completed['result']['reference_mode'] == 'same_identity'
        assert completed['result']['reference_artifact_id'] == 'uploaded-reference'
    assert len(calls) == count
    assert len({params['seed'] for _, params in calls}) == count
    normalized = []
    for model, params in calls:
        params = dict(params); params.pop('seed')
        normalized.append((model, params))
    assert all(item == normalized[0] for item in normalized)
    # Group presentation is allowed; source configuration/status/seed stay fixed.
    assert service._job_snapshot(service._jobs[first['id']]) == source_job


@pytest.mark.parametrize('context', [None, {'kind': 'image', 'image_count': 2}])
def test_missing_or_ambiguous_reference_never_generates(runtime, context):
    _, client, source, calls = runtime
    response = client.post('/api/chat/actions', json=request(source, file_context=context))
    result = response.json()
    assert result['status'] == 'failed'
    assert 'Referenzbild' in result['error']
    assert not calls


def test_no_available_edit_provider_never_falls_back_to_juggernaut(runtime, monkeypatch):
    native, client, source, calls = runtime
    monkeypatch.setattr(service, 'availability', lambda _: (False, 'incompatible CLI'))
    result = client.post('/api/chat/actions', json=request(source)).json()
    job = wait(native, result['data']['job']['id'])
    assert job['status'] == 'failed'
    assert 'Referenzbilder' in job['error']
    assert not calls


def test_current_upload_beats_active_artifact(runtime, monkeypatch):
    native, client, source, calls = runtime
    monkeypatch.setattr(agent, '_resolve_image_artifact_source', lambda *_: pytest.fail('Used active image instead of current upload'))
    result = client.post('/api/chat/actions', json=request(source, active_artifact_id='image-1234567890-abcdef123456')).json()
    completed = wait(native, result['data']['job']['id'])
    assert completed['status'] == 'completed'
    assert completed['result']['reference_artifact_id'] == 'uploaded-reference'
    assert calls[0][1]['source_path'] == str(source)


def test_selected_artifact_without_current_upload(runtime, monkeypatch):
    native, client, source, calls = runtime
    selected = []
    def resolve(artifact_id):
        selected.append(artifact_id)
        return source
    monkeypatch.setattr(agent, '_resolve_image_artifact_source', resolve)
    result = client.post('/api/chat/actions', json=request(source, file_context=None,
        active_artifact_id='image-1234567890-abcdef123456')).json()
    assert wait(native, result['data']['job']['id'])['status'] == 'completed'
    assert selected == ['image-1234567890-abcdef123456']
    assert calls[0][1]['source_path'] == str(source)


def test_optimizer_cannot_remove_reference_semantics(runtime, monkeypatch):
    native, client, source, calls = runtime
    monkeypatch.setattr(agent, 'translate_media_prompt_to_english', lambda _: 'A person in an office')
    result = client.post('/api/chat/actions', json=request(source, prompt='Create an image resembling this person.')).json()
    job = wait(native, result['data']['job']['id'])
    assert job['result']['reference_mode'] == 'resemblance'
    assert 'visual reference for recognizable resemblance' in calls[0][1]['prompt']
    assert calls[0][1]['source_path'] == str(source)


def test_classic_edit_person_removal_stays_classic(runtime):
    native, client, source, calls = runtime
    result = client.post('/api/chat/actions', json=request(source, prompt='Entferne diese Person.', image_options={'seed': 19})).json()
    completed = wait(native, result['data']['job']['id'])
    assert completed['result']['semantic_operation'] == 'edit'
    assert completed['result']['reference_used'] is False


@pytest.mark.parametrize('restart', [False, True])
def test_reference_variant_retry_keeps_completed_slots_and_planned_seeds(runtime, monkeypatch, restart):
    native, client, source, calls = runtime
    result = client.post('/api/chat/actions', json=request(source)).json()
    first = wait(native, result['data']['job']['id'])
    original = service.run_provider
    failures = []
    def fail_once(model, params, output, **kwargs):
        if len(calls) == 2 and not failures:
            failures.append(params['seed'])
            raise RuntimeError('Synthetic failure')
        return original(model, params, output, **kwargs)
    monkeypatch.setattr(service, 'run_provider', fail_once)
    payload = {'base_job_id': first['id'], 'count': 4, 'chat_id': 'reference-test', 'chat_revision': 0}
    group = native.post('/jobs/variants', json=payload).json()
    for job in group['jobs']:
        wait(native, job['id'])
    completed_id = service._jobs[group['jobs'][0]['id']]['result']['id']
    planned = [service._jobs[job['id']]['seed'] for job in group['jobs']]
    retry_payload = {**payload, 'variant_group_id': group['variant_group_id']}
    if restart:
        from image_variants import install, VariantBatch
        service._jobs.clear()
        routes_before = list(service.app.router.routes)
        fresh_handler = install(service)
        service.app.router.routes[:] = routes_before
        retry_group = fresh_handler(VariantBatch(**retry_payload))
    else:
        retry = native.post('/jobs/variants', json=retry_payload)
        assert retry.status_code == 202
        retry_group = retry.json()
    for job in retry_group['jobs']:
        assert wait(native, job['id'])['status'] == 'completed'
    assert len(calls) == 4
    assert service._jobs[group['jobs'][0]['id']]['result']['id'] == completed_id
    assert [service._jobs[job['id']]['seed'] for job in group['jobs']] == planned
    assert failures == [planned[1]]



def test_backend_reference_followup_without_frontend_mode(runtime):
    native, client, source, calls = runtime
    payload = request(source, prompt='Jetzt draußen im Regen.', file_context={
        'kind': 'image', 'stored_path': str(source), 'reference_mode': 'same_identity',
        'reference_artifact_id': 'uploaded-reference'})
    result = client.post('/api/chat/actions', json=payload).json()
    job = wait(native, result['data']['job']['id'])
    assert job['result']['reference_mode'] == 'same_identity'
    assert calls[0][1]['source_path'] == str(source)


@pytest.mark.parametrize('use_variant', [False, True])
def test_public_reference_job_recovers_private_original_source(runtime, use_variant):
    native, client, source, calls = runtime
    started = client.post('/api/chat/actions', json=request(source)).json()
    job = wait(native, started['data']['job']['id'])
    if use_variant:
        group = client.post('/api/image/jobs/variants', json={
            'base_job_id': job['id'], 'count': 3,
            'chat_id': 'reference-test', 'chat_revision': 0}).json()
        job = wait(native, group['jobs'][-1]['data']['job']['id'])
    public = client.get('/api/image/jobs/' + job['id']).json()
    artifact = public['artifacts'][0]
    assert 'source_path' not in artifact
    assert 'source_path' not in public['data']['job']['result']
    assert str(source) not in str(public)
    assert artifact['reference_source_job_id'] == job['id']
    # Original relationship comes from the private record, not client metadata.
    payload = request(source, prompt='Jetzt draußen im Regen.', file_context={
        'kind': 'image', 'artifact_id': artifact['artifact_id'],
        'reference_source_job_id': artifact['reference_source_job_id'],
        'reference_artifact_id': 'untrusted-client-value',
        'reference_mode': artifact['reference_mode']},
        image_options={'seed': 42})
    if not use_variant:
        payload['action'] = 'image_reference_generate'
        payload['reference_mode'] = artifact['reference_mode']
        del payload['file_context']['artifact_id']
    # Resolve after native jobs have been evicted/restarted.
    service._jobs.clear()
    response = client.post('/api/chat/actions', json=payload)
    assert response.status_code == 200, response.text
    regenerated = wait(native, response.json()['data']['job']['id'])
    assert regenerated['status'] == 'completed'
    assert regenerated['result']['reference_artifact_id'] == 'uploaded-reference'
    assert regenerated['result']['reference_mode'] == 'same_identity'
    assert regenerated['result']['id'] != artifact['image_id']
    assert calls[-1][1]['source_path'] == str(source)
    assert calls[-1][1]['seed'] == 42


@pytest.mark.parametrize('failure', ['missing', 'invalid', 'foreign_chat', 'stale_revision'])
def test_reference_job_source_never_falls_back_to_generated_artifact(runtime, failure):
    native, client, source, calls = runtime
    started = client.post('/api/chat/actions', json=request(source)).json()
    job = wait(native, started['data']['job']['id'])
    identifier = job['id']
    if failure == 'missing':
        identifier = '0' * 24
    elif failure == 'invalid':
        identifier = '../private'
    payload = request(source, file_context={
        'kind': 'image', 'artifact_id': 'image-' + job['result']['id'],
        'reference_source_job_id': identifier,
        'reference_mode': 'same_identity'})
    if failure == 'foreign_chat':
        payload['chat_id'] = 'other-chat'
    elif failure == 'stale_revision':
        payload['chat_revision'] = 1
    response = client.post('/api/chat/actions', json=payload)
    assert response.status_code == 200
    assert response.json()['status'] == 'failed'
    expected = ('Ungültige Image-Job-ID' if failure == 'invalid' else
                'Ursprüngliches Referenzbild ist nicht verfügbar. Bitte erneut anhängen.')
    assert response.json()['error'] == expected
    assert response.json()['artifacts'] == []
    assert len(calls) == 1
    # An explicit current upload has priority even over an unavailable record.
    payload = request(source)
    payload['file_context']['reference_source_job_id'] = identifier
    result = client.post('/api/chat/actions', json=payload).json()
    assert wait(native, result['data']['job']['id'])['status'] == 'completed'
    assert calls[-1][1]['source_path'] == str(source)


def test_queue_public_reference_result_hides_source_without_mutating_private_job():
    from agent import media_queue
    private = {'id': 'a' * 24, 'status': 'completed', 'result': {
        'semantic_operation': 'reference_generate', 'source_path': '/private/reference.png'}}
    assert 'source_path' not in media_queue._public(private)['result']
    assert private['result']['source_path'] == '/private/reference.png'


def test_unknown_reference_errors_are_safe(runtime, monkeypatch):
    _, client, source, calls = runtime
    def fail(*args):
        raise RuntimeError('/private/secret Traceback')
    monkeypatch.setattr(agent, '_image_edit_payload', fail)
    result = client.post('/api/chat/actions', json=request(source)).json()
    assert result['status'] == 'failed'
    assert '/private' not in result['error'] and 'Traceback' not in result['error']
    assert not calls


def test_resolver_skips_unavailable_edit_model(runtime, monkeypatch):
    native, client, source, calls = runtime
    data = service.registry.load_registry()
    bad = {**data['models'][1], 'id': 'incompatible-edit'}
    monkeypatch.setattr(service.registry, 'load_registry', lambda: {**data, 'models': [bad, *data['models']]})
    monkeypatch.setattr(service, 'availability', lambda m: (m['id'] != 'incompatible-edit', 'local contract'))
    result = client.post('/api/chat/actions', json=request(source)).json()
    assert wait(native, result['data']['job']['id'])['status'] == 'completed'
    assert calls[0][0]['id'] == 'local-edit'
