"""Compare actual provider inputs, including prompts; never emit them to logs."""
import copy
import threading
import time
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

import image_service as service
from agent import app as agent
from quality_profiles import resolve_image_profile, dimensions_for_long_edge


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "OUTPUT", tmp_path)
    monkeypatch.setattr(agent, "IMAGE_DIRECTORY", tmp_path)
    monkeypatch.setattr(service.runtime_coordinator, "image_runtime", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(service, "_variant_active_keys", service._variant_active_keys)
    service._jobs.clear()
    yield TestClient(service.app, base_url="http://localhost")
    for job in list(service._jobs.values()):
        thread = job.get("_thread")
        if thread and thread.ident is not None:
            thread.join(5)
    service._jobs.clear()


def model(family, model_id):
    return {"id": model_id, "provider": "sdxl", "model_family": family,
            "base_model": "sdxl", "default_steps": 28, "default_guidance": 4.5,
            "quantization": "fp16", "loras": [{"enabled": True, "path": "local-lora", "scale": 0.8}]}


def wait(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get('/jobs/' + job_id).json()
        if job['status'] in {'completed', 'failed', 'cancelled'}:
            thread = service._jobs[job_id].get('_thread')
            if thread and thread.ident is not None:
                thread.join(5)
            return job
        time.sleep(0.005)
    pytest.fail('Image job timed out')


def base(client, **options):
    payload = {"prompt": "An optimized studio photograph of a red apple",
               "original_prompt": "Erstelle ein Bild eines roten Apfels",
               "negative_prompt": "blurry, malformed", "model": "auto", "width": 512,
               "height": 512, "auto_size": True, "quality": "quality", **options}
    response = client.post('/jobs', json={"operation": "generate", "payload": payload,
                                         "chat_id": "variants-test", "chat_revision": 0})
    assert response.status_code == 202, response.text
    result = wait(client, response.json()['id'])
    assert result['status'] == 'completed', result.get('error')
    return result, payload


def batch(client, first, **options):
    response = client.post('/jobs/variants', json={"base_job_id": first['id'], "count": 6,
                                                  "chat_id": "variants-test", "chat_revision": 0,
                                                  **options})
    assert response.status_code == 202, response.text
    result = response.json()
    for job in result['jobs']:
        wait(client, job['id'])
    return result


@pytest.mark.parametrize('family,model_id,quality,width,height,expected', [
    ('qwen-image21', 'qwen21', 'quality', 512, 512, (1024, 1024)),
    ('qwen-image21', 'qwen21', 'quality', 432, 768, (576, 1024)),
    ('sdxl', 'juggernaut-xl', 'standard', 768, 432, (1024, 576)),
    ('sdxl', 'juggernaut-xl', 'quality', 512, 512, (1216, 1216)),
])
def test_six_canonical_generate_variants(runtime, monkeypatch, family, model_id, quality, width, height, expected):
    selected = model(family, model_id)
    routed = []
    profiles = []
    calls = []
    active = 0
    def route(*args):
        routed.append(args)
        return copy.deepcopy(selected)
    def provider(resolved_model, params, output, operation='generate', **kwargs):
        nonlocal active
        active += 1
        assert active == 1, 'Heavy jobs must run sequentially'
        calls.append((operation, copy.deepcopy(resolved_model), copy.deepcopy(params)))
        time.sleep(0.002)
        output.write_bytes(b'local test image')
        active -= 1
    monkeypatch.setattr(service, '_generation_model', route)
    def profile(*args):
        profiles.append(args)
        return resolve_image_profile(*args)
    monkeypatch.setattr(service, 'resolve_image_profile', profile)
    monkeypatch.setattr(service, 'run_provider', provider)
    first, payload = base(runtime, quality=quality, width=width, height=height)
    # Change both registry defaults and profiles after image 1: the batch must stay pinned.
    selected['id'] = 'different-model'
    selected['loras'] = []
    monkeypatch.setattr(service, 'resolve_image_profile', lambda *_: pytest.fail('Profile resolved again'))
    result = batch(runtime, first)
    assert len(calls) == 6
    assert len(routed) == 1
    assert len(profiles) == 1
    assert all(call[0] == 'generate' for call in calls)
    assert all('source_path' not in call[2] for call in calls)
    reference = copy.deepcopy(calls[0])
    reference[2].pop('seed')
    for call in calls:
        normalized = copy.deepcopy(call)
        normalized[2].pop('seed')
        assert normalized == reference  # Exact prompts, LoRAs, config, negative prompt and policy.
        assert (call[2]['width'], call[2]['height']) == expected
        assert call[2]['auto_size'] is True
    assert len({call[2]['seed'] for call in calls}) == 6
    first_artifact = agent._image_job_tool_result(runtime.get('/jobs/' + first['id']).json())['artifacts'][0]
    assert first_artifact['original_prompt'] == payload['original_prompt']
    assert first_artifact['negative_prompt'] == payload['negative_prompt']
    assert first_artifact['generation_job_id'] == first['id']
    assert 'variant_index' not in first_artifact
    assert runtime.get('/jobs/' + first['id']).json() == first
    assert result['base_job']['result']['variant_index'] == 1
    for index, job in enumerate(result['jobs'], 2):
        resolved = runtime.get('/jobs/' + job['id']).json()
        artifact = agent._image_job_tool_result(resolved)['artifacts'][0]
        assert artifact['variant_group_id'] == result['variant_group_id']
        assert artifact['variant_index'] == index
        assert artifact['variant_count'] == 6
        assert artifact['resolved_model'] == model_id
        assert artifact['original_prompt'] == payload['original_prompt']
        assert artifact['quality_profile'] == first_artifact['quality_profile']
        assert artifact['width'] == first_artifact['width']
        assert artifact['height'] == first_artifact['height']


def test_failure_retry_only_missing_and_recover_retained_metadata(runtime, monkeypatch):
    calls = []
    fail = True
    def provider(m, params, output, **kwargs):
        nonlocal fail
        calls.append(params['seed'])
        if len(calls) == 4 and fail:
            fail = False
            raise RuntimeError('Synthetic provider failure')
        output.write_bytes(b'image')
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    monkeypatch.setattr(service, 'run_provider', provider)
    first, _ = base(runtime, seed=2**32 - 2)
    result = batch(runtime, first)
    statuses = [runtime.get('/jobs/' + job['id']).json()['status'] for job in result['jobs']]
    assert statuses == ['completed', 'completed', 'failed', 'failed', 'failed']
    completed_ids = [service._jobs[job['id']]['result']['id'] for job in result['jobs'][:2]]
    # The batch survives eviction/restart of the ordinary in-memory jobs.
    service._jobs.clear()
    from image_variants import install, VariantBatch
    from image_variants import load_record, save_record
    stale = load_record(service.OUTPUT, 'group-' + result['variant_group_id'])
    stale['jobs'][0].update(status='queued', result=None)
    save_record(service.OUTPUT, 'group-' + result['variant_group_id'], stale)
    routes_before = list(service.app.router.routes)
    fresh_handler = install(service)
    service.app.router.routes[:] = routes_before  # Invoke restored orchestration directly.
    retry = fresh_handler(VariantBatch(base_job_id=first['id'], count=6,
                                      chat_id='variants-test', chat_revision=0,
                                      variant_group_id=result['variant_group_id']))
    for job in retry['jobs']:
        wait(runtime, job['id'])
    assert len(calls) == 7  # 1,2,3,failed4 + retry4,5,6
    assert calls == [2**32 - 2, 2**32 - 1, 0, 1, 1, 2, 3]
    assert [service._jobs[job['id']]['result']['id'] for job in retry['jobs'][:2]] == completed_ids
    assert all(runtime.get('/jobs/' + job['id']).json()['status'] == 'completed' for job in retry['jobs'])
    fresh_handler(VariantBatch(base_job_id=first['id'], count=6, chat_id='variants-test',
                               chat_revision=0, variant_group_id=result['variant_group_id']))
    assert len(calls) == 7  # Completed retry is idempotent.


def test_batch_owns_lock_cancellation_keeps_base(runtime, monkeypatch):
    entered = threading.Event()
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    monkeypatch.setattr(service, 'run_provider', lambda m, p, out, **kw: out.write_bytes(b'image'))
    first, _ = base(runtime)
    def blocking(m, p, out, cancel_event, **kwargs):
        entered.set()
        assert cancel_event.wait(2)
        raise service.ProviderCancelled('cancel')
    monkeypatch.setattr(service, 'run_provider', blocking)
    response = runtime.post('/jobs/variants', json={"base_job_id": first['id'], "count": 6,
                                                   "chat_id": "variants-test", "chat_revision": 0})
    assert response.status_code == 202
    jobs = response.json()['jobs']
    assert entered.wait(2)
    conflict = runtime.post('/jobs', json={"operation": "generate", "payload": {"prompt": "another image"},
                                         "chat_id": "variants-test", "chat_revision": 0})
    assert conflict.status_code == 409
    assert runtime.post('/jobs/' + jobs[0]['id'] + '/cancel').status_code == 200
    assert wait(runtime, jobs[-1]['id'])['status'] == 'cancelled'
    assert runtime.get('/jobs/' + first['id']).json()['status'] == 'completed'
    assert not service._lock.locked()


def test_variant_chat_revision_and_generate_semantics(runtime, monkeypatch):
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    monkeypatch.setattr(service, 'run_provider', lambda m, p, out, **kw: out.write_bytes(b'image'))
    first, _ = base(runtime)
    assert runtime.post('/jobs/variants', json={"base_job_id": first['id'], "count": 6,
                                               "chat_id": "other-chat", "chat_revision": 0}).status_code == 404
    service._jobs[first['id']]['operation'] = 'edit'
    assert runtime.post('/jobs/variants', json={"base_job_id": first['id'], "count": 6,
                                               "chat_id": "variants-test", "chat_revision": 0}).status_code == 409


@pytest.mark.parametrize('family,model_id,quality,width,height,old_resolution', [
    ('qwen-image21', 'qwen21', 'quality', 512, 512, (512, 512)),
    ('qwen-image21', 'qwen21', 'quality', 432, 768, (432, 768)),
    ('sdxl', 'juggernaut-xl', 'standard', 768, 432, (768, 432)),
])
def test_reproduce_old_request_resolution_regression(runtime, monkeypatch, family, model_id, quality, width, height, old_resolution):
    monkeypatch.setattr(service, '_generation_model', lambda *_: model(family, model_id))
    monkeypatch.setattr(service, 'run_provider', lambda m, p, out, **kw: out.write_bytes(b'image'))
    first, payload = base(runtime, quality=quality, width=width, height=height)
    # Previous picker overwrote the artifact's resolved dimensions, and regeneration disabled auto-size.
    old = service._generate_result(service.Generate(**{**payload, 'auto_size': False, 'seed': 123}))
    assert (old['width'], old['height']) == old_resolution
    assert (first['result']['width'], first['result']['height']) == dimensions_for_long_edge(
        width, height, resolve_image_profile(model(family, model_id), quality)['long_edge'])
    assert (old['width'], old['height']) != (first['result']['width'], first['result']['height'])


def test_agent_variants_proxy_validates_revision_and_never_optimizes(runtime, monkeypatch):
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    monkeypatch.setattr(service, 'run_provider', lambda m, p, out, **kw: out.write_bytes(b'image'))
    first, _ = base(runtime)
    monkeypatch.setattr(agent, 'validate_chat_id', lambda _: None)
    monkeypatch.setattr(agent, 'read_chat', lambda _: {'revision': 0})
    monkeypatch.setattr(agent, '_image_generate_payload', lambda *_: pytest.fail('Optimizer path was used'))
    def proxy(method, path, payload=None, **kwargs):
        response = runtime.request(method, path, json=payload)
        assert response.status_code < 400, response.text
        return response.json()
    monkeypatch.setattr(agent.image_api, 'request', proxy)
    client = TestClient(agent.app, base_url='http://localhost')
    payload = {'base_job_id': first['id'], 'count': 3, 'chat_id': 'variants-test', 'chat_revision': 0}
    assert client.post('/api/image/jobs/variants', json={**payload, 'chat_revision': 1}).status_code == 409
    assert client.post('/api/image/jobs/variants', json={**payload, 'count': 7}).status_code == 422
    response = client.post('/api/image/jobs/variants', json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['base']['artifacts'][0]['variant_index'] == 1
    assert len(result['jobs']) == 2
    for index, tool_result in enumerate(result['jobs'], 2):
        job_id = tool_result['data']['job']['id']
        wait(runtime, job_id)
        polled = client.get('/api/image/jobs/' + job_id).json()
        assert polled['tool'] == 'image_generate'
        assert polled['artifacts'][0]['variant_index'] == index
        assert polled['artifacts'][0]['variant_count'] == 3
        assert polled['artifacts'][0]['generation_job_id'] == job_id


@pytest.fixture
def simple_source(runtime, monkeypatch):
    calls = []
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    def provider(m, params, output, **kwargs):
        calls.append(copy.deepcopy(params))
        output.write_bytes(b'image')
    monkeypatch.setattr(service, 'run_provider', provider)
    first, _ = base(runtime, seed=123)
    return first, calls


def test_optional_persistence_failure_preserves_single_image(runtime, monkeypatch):
    import image_variants
    monkeypatch.setattr(service, '_generation_model', lambda *_: model('sdxl', 'juggernaut-xl'))
    monkeypatch.setattr(service, 'run_provider', lambda m, p, out, **kw: out.write_bytes(b'image'))
    def fail(*args):
        raise OSError('private path must not leak')
    monkeypatch.setattr(image_variants, 'save_record', fail)
    first, _ = base(runtime)
    assert first['status'] == 'completed'
    assert image_variants.valid_image_file(first)
    assert first['variants_available'] is False
    response = runtime.post('/jobs/variants', json={'base_job_id': first['id'], 'count': 3,
        'chat_id': 'variants-test', 'chat_revision': 0})
    assert response.status_code == 409
    assert 'private path' not in response.text


@pytest.mark.parametrize('failure', ['persistence', 'thread'])
def test_start_failure_has_no_orphan(runtime, monkeypatch, simple_source, failure):
    import image_variants
    first, calls = simple_source
    def fail(*args, **kwargs):
        raise OSError('/private/secret traceback')
    if failure == 'persistence':
        monkeypatch.setattr(image_variants, 'save_record', fail)
    else:
        original_start = image_variants.threading.Thread.start
        def fail_variant_thread(thread):
            if thread.name.startswith('image-variants-'):
                fail()
            return original_start(thread)
        monkeypatch.setattr(image_variants.threading.Thread, 'start', fail_variant_thread)
    response = runtime.post('/jobs/variants', json={'base_job_id': first['id'], 'count': 3,
        'chat_id': 'variants-test', 'chat_revision': 0})
    assert response.status_code == 503
    assert '/private' not in response.text and 'traceback' not in response.text
    assert not service._lock.locked()
    assert service._active_job_id is None
    assert len(calls) == 1
    assert all(job['status'] in {'completed', 'failed'} for job in service._jobs.values())
    assert runtime.get('/jobs/' + first['id']).json() == first


@pytest.mark.parametrize('file_state', ['present', 'missing', 'empty', 'directory'])
def test_restored_slot_validity_and_seed_retry(runtime, monkeypatch, simple_source, file_state):
    from pathlib import Path
    from image_variants import install, VariantBatch
    first, calls = simple_source
    group = batch(runtime, first, count=3)
    slot = runtime.get('/jobs/' + group['jobs'][0]['id']).json()
    other = runtime.get('/jobs/' + group['jobs'][1]['id']).json()
    path = Path(slot['result']['path'])
    if file_state == 'missing':
        path.unlink()
    elif file_state == 'empty':
        path.write_bytes(b'')
    elif file_state == 'directory':
        path.unlink(); path.mkdir()
    service._jobs.clear()
    routes_before = list(service.app.router.routes)
    handler = install(service)
    service.app.router.routes[:] = routes_before
    result = handler(VariantBatch(base_job_id=first['id'], count=3, chat_id='variants-test',
        chat_revision=0, variant_group_id=group['variant_group_id']))
    if file_state != 'present':
        wait(runtime, slot['id'])
        assert len(calls) == 4
        assert calls[-1] == calls[1]
        assert service._jobs[slot['id']]['result']['id'] != slot['result']['id']
        assert service._jobs[other['id']]['result'] == other['result']
    else:
        assert len(calls) == 3
        assert result['jobs'][0]['result'] == slot['result']
    assert result['base_job']['result']['id'] == first['result']['id']


def test_private_retention_pins_active_and_retained_dependencies(runtime, monkeypatch, simple_source):
    from image_variants import save_record, prune_records, load_record
    first, _ = simple_source
    group = batch(runtime, first, count=3)
    monkeypatch.setattr(service, '_MAX_RETAINED_JOBS', 2)
    monkeypatch.setattr(service, '_variant_active_keys', lambda: {'group-' + group['variant_group_id']})
    for index in range(10):
        key = 'job-' + f'{index:024x}'
        source_record = load_record(service.OUTPUT, 'job-' + first['id'])
        source_record['job']['id'] = f'{index:024x}'
        save_record(service.OUTPUT, key, source_record)
        gid = f'{index:024x}'
        group_record = load_record(service.OUTPUT, 'group-' + group['variant_group_id'])
        group_record.update(id=gid, base_id=f'{index:024x}', jobs=[])
        save_record(service.OUTPUT, 'group-' + gid, group_record)
    prune_records(service)
    assert load_record(service.OUTPUT, 'group-' + group['variant_group_id'])
    assert load_record(service.OUTPUT, 'job-' + first['id'])
    for job in group['jobs']:
        assert load_record(service.OUTPUT, 'job-' + job['id'])
    assert len(list((service.OUTPUT / '.variants').glob('group-*.json'))) <= 3
    assert len(list((service.OUTPUT / '.variants').glob('job-*.json'))) <= 7
    assert not list((service.OUTPUT / '.variants').glob('*.tmp'))


def test_queue_artifact_uses_native_source_job_id(runtime, simple_source):
    first, _ = simple_source
    queued = {**first, 'id': 'a'*24, 'native_job_id': first['id']}
    artifact = agent._image_job_tool_result(queued)['artifacts'][0]
    assert artifact['generation_job_id'] == first['id']
    assert queued['id'] == 'a'*24


def test_group_status_and_cancellation_scope(runtime, monkeypatch, simple_source):
    first, calls = simple_source
    entered = threading.Event()
    attempts = []
    def blocked(m, p, out, cancel_event, **kwargs):
        attempts.append(p['seed'])
        if len(attempts) == 1:
            out.write_bytes(b'completed variant')
            return
        entered.set()
        assert cancel_event.wait(3)
        raise service.ProviderCancelled('cancel')
    monkeypatch.setattr(service, 'run_provider', blocked)
    response = runtime.post('/jobs/variants', json={'base_job_id': first['id'], 'count': 3,
        'chat_id': 'variants-test', 'chat_revision': 0})
    group = response.json(); gid = group['variant_group_id']
    assert entered.wait(2)
    path = '/variant-groups/' + gid
    assert runtime.get(path, params={'chat_id': 'wrong', 'chat_revision': 0}).status_code == 404
    identity = {'chat_id': 'variants-test', 'chat_revision': 0}
    assert runtime.get(path, params=identity).json()['status'] == 'running'
    assert runtime.post(path + '/cancel', params=identity).status_code == 200
    wait(runtime, group['jobs'][-1]['id'])
    status = runtime.get(path, params=identity).json()
    assert status['status'] == 'cancelled'
    assert status['jobs'][0]['status'] == 'completed'
    from image_variants import valid_image_file
    assert valid_image_file(status['jobs'][0])
    assert status['jobs'][1]['status'] == 'cancelled'
    assert runtime.get('/jobs/' + first['id']).json() == first
    assert len(calls) == 1



def test_include_base_false_preserves_source_and_private_configuration(runtime, simple_source):
    first, calls = simple_source
    frozen = copy.deepcopy(service._jobs[first['id']]['_canonical'])
    result = batch(runtime, first, count=3, include_base=False)
    assert len(result['jobs']) == 3
    assert len(calls) == 4
    assert len({call['seed'] for call in calls}) == 4
    assert runtime.get('/jobs/' + first['id']).json() == first
    assert service._jobs[first['id']]['_canonical'] == frozen
    assert 'variant_group_id' not in result['base_job']['result']
    assert all('_canonical' not in job for job in result['jobs'])


def test_agent_group_status_validates_revision(runtime, monkeypatch, simple_source):
    first, _ = simple_source
    group = batch(runtime, first, count=3)
    monkeypatch.setattr(agent, 'validate_chat_id', lambda _: None)
    monkeypatch.setattr(agent, 'read_chat', lambda _: {'revision': 0})
    def proxy(method, path, payload=None, **kwargs):
        response = runtime.request(method, path, json=payload)
        assert response.status_code < 400
        return response.json()
    monkeypatch.setattr(agent.image_api, 'request', proxy)
    client = TestClient(agent.app, base_url='http://localhost')
    path = '/api/image/variant-groups/' + group['variant_group_id']
    assert client.get(path, params={'chat_id': 'variants-test', 'chat_revision': 1}).status_code == 409
    result = client.get(path, params={'chat_id': 'variants-test', 'chat_revision': 0}).json()
    assert result['status'] == 'completed'
    assert len(result['jobs']) == 2
    assert all('_canonical' not in job['data']['job'] for job in result['jobs'])


@pytest.mark.parametrize('record', ['invalid json', '[]', '{"canonical":{},"job":{}}'])
def test_corrupt_source_record_fails_safely(runtime, simple_source, record):
    first, _ = simple_source
    path = service.OUTPUT / '.variants' / ('job-' + first['id'] + '.json')
    path.write_text(record)
    service._jobs.clear()
    response = runtime.post('/jobs/variants', json={'base_job_id': first['id'], 'count': 3,
        'chat_id': 'variants-test', 'chat_revision': 0})
    assert response.status_code == 404
    from image_variants import valid_image_file
    assert valid_image_file(first)


def test_private_record_permissions(runtime, simple_source):
    first, _ = simple_source
    directory = service.OUTPUT / '.variants'
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / ('job-' + first['id'] + '.json')).stat().st_mode & 0o777 == 0o600
