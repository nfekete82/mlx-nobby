"""Mock inference through the real service, source validation and CLI adapters."""
from contextlib import nullcontext
from pathlib import Path
import threading

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

import image_service as service
import image_providers as providers
import image_registry as registry
from backend.media_intent import decide_media_intent
from agent import app as agent
from agent.coding_benchmark import CODING_TASKS, score
from agent.intelligent_routing import select_chat_role


@pytest.fixture
def edit_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'OUTPUT', tmp_path)
    model = next(m for m in registry.builtin_models() if m['model_family'] == 'qwen-image21-edit')
    model = dict(model, enabled=True)
    monkeypatch.setattr(service, '_edit_model', lambda *a, **kw: model)
    monkeypatch.setattr(service, 'availability', lambda _: (True, 'ready'))
    monkeypatch.setattr(providers, 'model_directory', lambda _: tmp_path)
    flags = '--model --prompt --width --height --steps --seed --output --image-paths --guidance --quantize --negative-prompt --mask-image --auto-mask --strength --use-kv-cache --no-use-kv-cache --use-step-cache --no-use-step-cache --enhance-prompt --verify --mlx-cache-limit-gb --low-ram --output-resolution --vae-tiling'.split()
    probe = lambda _: {'available': True, 'supported_flags': frozenset(flags), 'error': None}
    monkeypatch.setattr(providers, 'mflux_contract', lambda *a: (True, 'ready'))
    monkeypatch.setattr(providers, 'probe_mflux_cli', probe)
    monkeypatch.setattr(service.runtime_coordinator, 'ensure_model_load_allowed', lambda _: None)
    sources = []
    for index in range(10):
        path = tmp_path / f'ref-{index}.png'
        Image.new('RGB', (512, 384), (index, 0, 0)).save(path)
        sources.append(path)
    return tmp_path, sources, model


@pytest.mark.parametrize('count', [1, 2, 10])
def test_ordered_references_and_cleanup(edit_runtime, monkeypatch, count):
    root, sources, model = edit_runtime
    before = [p.read_bytes() for p in sources]
    seen = []
    def render(selected, params, output, **kw):
        command = providers.mflux_command(selected, params, output)
        paths = command[command.index('--image-paths') + 1:command.index('--prompt')]
        assert len(paths) == count
        assert paths == params['source_paths']
        assert not set(paths) & {str(p) for p in sources}
        for index, path in enumerate(paths):
            with Image.open(path) as image:
                assert image.getpixel((0, 0))[0] == index
        seen.extend(paths)
        Image.new('RGB', (params['width'], params['height'])).save(output)
    monkeypatch.setattr(service, 'run_provider', render)
    result = service._edit_result(service.Edit(prompt='Combine the people', source_paths=[str(p) for p in sources[:count]]))
    assert result['reference_count'] == count
    assert result['source_paths'] == [str(p) for p in sources[:count]]
    assert Path(result['path']).exists()
    assert all(not Path(p).exists() for p in seen)
    assert not list(root.glob('.edit-source-*'))
    assert [p.read_bytes() for p in sources] == before


@pytest.mark.parametrize('failure', ['provider', 'cancel', 'callback'])
def test_cleanup_on_every_failure(edit_runtime, monkeypatch, failure):
    root, sources, _ = edit_runtime
    def fail(*args, **kw):
        if failure == 'cancel':
            raise providers.ProviderCancelled('cancelled')
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(service, 'run_provider', fail)
    with pytest.raises((RuntimeError, providers.ProviderCancelled)):
        service._edit_result(service.Edit(prompt='Combine', source_paths=[str(p) for p in sources[:2]]),
                             prepared_callback=fail if failure == 'callback' else None)
    assert not list(root.glob('.edit-source-*'))
    assert all(p.exists() for p in sources)


@pytest.mark.parametrize('kind', ['corrupt', 'wrong_format', 'outside', 'bomb'])
def test_source_validation(edit_runtime, kind, tmp_path_factory):
    root, _, _ = edit_runtime
    source = root / 'bad.png'
    if kind == 'corrupt': source.write_bytes(b'not an image')
    elif kind == 'wrong_format': Image.new('RGB', (32, 32)).save(source, 'BMP')
    elif kind == 'bomb': Image.new('1', (6000, 5000)).save(source, 'PNG')
    else:
        source = tmp_path_factory.mktemp('outside') / 'bad.png'
        Image.new('RGB', (32, 32)).save(source)
    with pytest.raises(HTTPException) as error:
        service.validate_edit_source(str(source))
    assert error.value.status_code == 422


def test_reference_count_and_conflicting_source_contract():
    for payload in ({'source_paths': []}, {'source_paths': ['x'] * 11},
                    {'source_path': 'a', 'source_paths': ['b']}, {},
                    {'source_path': 'a', 'use_step_cache': True, 'use_kv_cache': False}):
        with pytest.raises(ValidationError):
            service.Edit(prompt='Combine', **payload)


def test_options_and_mask_contract(edit_runtime, monkeypatch):
    root, sources, model = edit_runtime
    mask = root / 'mask.png'
    Image.new('L', (512, 384), 255).save(mask)
    seen = []
    def render(selected, params, output, **kw):
        command = providers.mflux_command(selected, params, output)
        for flag in ('--mask-image', '--strength', '--negative-prompt', '--use-step-cache', '--verify', '--enhance-prompt'):
            assert flag in command
        seen.append(params['mask_path'])
        assert params['mask_path'] != str(mask)
        Image.new('RGBA', (params['width'], params['height'])).save(output)
    monkeypatch.setattr(service, 'run_provider', render)
    service._edit_result(service.Edit(prompt='Repaint', source_paths=[str(sources[0])], mask_path=str(mask),
        strength=.5, negative_prompt='blur', guidance=2, use_step_cache=True, verify=True, enhance_prompt=True))
    assert mask.exists() and all(not Path(path).exists() for path in seen)
    assert not list(root.glob('.edit-source-*'))
    monkeypatch.setattr(providers, 'probe_mflux_cli', lambda _: {'supported_flags': frozenset()})
    with pytest.raises(providers.ProviderFailure, match='CLI unterstützt'):
        providers.mflux_command(model, {'source_path': str(sources[0]), 'width':512, 'height':384,
            'steps':20, 'guidance':2, 'seed':1, 'prompt':'test', 'strength':.5}, root/'out.png')


def test_composition_routes_and_payload_preserves_manual_model(edit_runtime):
    _, sources, _ = edit_runtime
    prompt = 'Setze Person 1 und Person 2 gemeinsam auf eine Parkbank'
    assert decide_media_intent(prompt, has_image=True).target == 'image_edit'
    request = agent.ChatActionRequest(prompt=prompt, file_context={'kind':'image', 'references':[
        {'stored_path': str(path)} for path in sources[:2]]}, image_options={'model':'manual-edit', 'strength':.7})
    payload = agent._image_edit_payload(request)
    assert payload['source_paths'] == [str(p) for p in sources[:2]]
    assert payload['model'] == 'manual-edit' and payload['strength'] == .7


def test_opt_in_role_selection_preserves_manual_choices():
    messages = [{'role':'user','content':'Refactor this Python code'}]
    assert select_chat_role(messages, {'chat':'manual'}, {'coding'}, enabled=True) == 'chat'
    assert select_chat_role(messages, {'chat':'auto'}, {'coding'}, enabled=True) == 'coding'
    assert select_chat_role(messages, {'chat':'auto'}, set(), enabled=True) == 'chat'
    assert select_chat_role(messages, {'chat':'auto'}, {'coding'}) == 'chat'
    assert select_chat_role([{'role':'user','content':'Hallo'}], {'chat':'auto'}, {'coding'}, enabled=True) == 'chat'


def test_coding_suite_has_strict_structured_and_grounded_checks():
    import json
    assert len({task['category'] for task in CODING_TASKS}) == 10
    for task in CODING_TASKS:
        assert score(task, json.dumps(task['expected']))
        assert not score(task, 'Here is the answer: ' + json.dumps(task['expected']))
        assert not score(task, '{}')


def test_references_are_recoverable_without_temporary_paths(edit_runtime, monkeypatch):
    root, sources, _ = edit_runtime
    records = []
    def render(model, params, output, **kw):
        Image.new('RGB', (params['width'], params['height'])).save(output)
    monkeypatch.setattr(service, 'run_provider', render)
    request = service.Edit(prompt='Use both people', source_paths=[str(p) for p in sources[:2]],
                           semantic_operation='reference_generate', reference_mode='same_identity')
    result = service._edit_result(request, resolved_callback=records.append)
    assert '.edit-source-' not in str(records)
    restored = service.Edit(**records[0]['request'])
    second = service._edit_result(restored, resolved=records[0])
    assert second['source_paths'] == result['source_paths']
    assert second['id'] != result['id']
    assert not list(root.glob('.edit-source-*'))


def test_wrong_size_mask_cleans_working_copies(edit_runtime):
    root, sources, _ = edit_runtime
    mask = root / 'small-mask.png'
    Image.new('L', (32,32),255).save(mask)
    with pytest.raises(HTTPException, match='Maske'):
        service._edit_result(service.Edit(prompt='Repaint', source_paths=[str(sources[0])], mask_path=str(mask)))
    assert not list(root.glob('.edit-source-*'))


def test_auto_model_requires_21_for_modern_options(edit_runtime, monkeypatch):
    _, sources, modern = edit_runtime
    legacy = {**modern, 'id':'legacy', 'model_family':'qwen-image-edit'}
    monkeypatch.undo()
    monkeypatch.setattr(service.registry, 'load_registry', lambda: {'default_model':'legacy','models':[legacy, modern]})
    monkeypatch.setattr(service, 'availability', lambda _: (True, 'ready'))
    assert service._edit_model('auto', modern=True)['id'] == modern['id']
    # Explicit manual choices reach provider validation, never another model.
    monkeypatch.setattr(service.registry, 'get_model', lambda _: legacy)
    assert service._edit_model('legacy', modern=True)['id'] == 'legacy'


def test_reference_payload_accepts_list_without_redundant_first_path(edit_runtime):
    _, sources, _ = edit_runtime
    request = agent.ChatActionRequest(prompt='Create an image of the same person',
        action='image_reference_generate', file_context={'kind':'image','references':[
            {'stored_path':str(p)} for p in sources[:2]]})
    payload = agent._image_edit_payload(request)
    assert payload['source_path'] == str(sources[0])
    assert payload['source_paths'] == [str(p) for p in sources[:2]]
    assert 'Use all 2 reference images' in payload['prompt']


def test_automatic_edit_prefers_available_osaurus_without_overriding_manual(monkeypatch):
    from image_registry import OSAURUS_QWEN21_EDIT_ID
    candidates = [
        dict(id='mflux-qwen-image-2.1-edit', provider='mflux',
             model_family='qwen-image21-edit', capabilities=['image_edit'],
             enabled=True),
        dict(id=OSAURUS_QWEN21_EDIT_ID, provider='mflux',
             model_family='qwen-image21-edit', capabilities=['image_edit'],
             enabled=True),
    ]
    monkeypatch.setattr(service.registry, 'load_registry',
                        lambda: {'models': candidates, 'default_model': candidates[0]['id']})
    monkeypatch.setattr(service, 'availability', lambda model: (True, 'ready'))
    assert service._edit_model('auto', multi_reference=True)['id'] == OSAURUS_QWEN21_EDIT_ID
    monkeypatch.setattr(service.registry, 'get_model',
                        lambda model_id: next(m for m in candidates if m['id'] == model_id))
    assert service._edit_model(candidates[0]['id'], multi_reference=True)['id'] == candidates[0]['id']


def test_auto_edit_skips_unavailable_osaurus(monkeypatch):
    from image_registry import OSAURUS_QWEN21_EDIT_ID
    candidates = [
        dict(id=OSAURUS_QWEN21_EDIT_ID, provider='mflux',
             model_family='qwen-image21-edit', capabilities=['image_edit'],
             enabled=True),
        dict(id='mflux-qwen-image-2.1-edit', provider='mflux',
             model_family='qwen-image21-edit', capabilities=['image_edit'],
             enabled=True),
    ]
    monkeypatch.setattr(service.registry, 'load_registry',
                        lambda: {'models': candidates, 'default_model': candidates[1]['id']})
    monkeypatch.setattr(service, 'availability',
                        lambda model: (model['id'] != OSAURUS_QWEN21_EDIT_ID, 'missing'))
    assert service._edit_model('auto', multi_reference=True)['id'] == candidates[1]['id']



@pytest.mark.parametrize("prompt", [
    "Erstelle ein gemeinsames fotorealistisches Bild der beiden Frauen aus den Referenzfotos, wie sie zusammen auf einem Bett liegen.",
    "Create an image with both people together on a bench",
    "Setz beide Personen gemeinsam auf eine Parkbank",
])
def test_auto_composition_payload_without_redundant_single_source(edit_runtime, prompt):
    _, sources, _ = edit_runtime
    context = {
        "kind": "image",
        "image_count": 2,
        "references": [
            {"kind": "image", "stored_path": str(path)} for path in sources[:2]
        ],
    }
    request = agent.ChatActionRequest(
        prompt=prompt, file_context=context,
        resolved_target="image_edit", image_options={"model": "auto"},
    )
    route = agent.preflight_chat_action(request)
    assert route["target"] == "image_edit"
    assert route["reference_mode"] == "same_identity"
    payload = agent._image_edit_payload(request)
    assert payload["semantic_operation"] == "reference_generate"
    assert payload["reference_mode"] == "same_identity"
    assert payload["source_path"] == str(sources[0])
    assert payload["source_paths"] == [str(path) for path in sources[:2]]
    assert payload["model"] == "auto"
    assert "Use all 2 reference images" in payload["prompt"]
    validated = service.Edit(**payload)
    assert validated.semantic_operation == "reference_generate"
    assert validated.source_paths == [str(path) for path in sources[:2]]


def test_single_edit_still_uses_regular_edit_payload(edit_runtime):
    _, sources, _ = edit_runtime
    request = agent.ChatActionRequest(
        prompt="Bearbeite den Hintergrund",
        file_context={"kind": "image", "stored_path": str(sources[0])},
        resolved_target="image_edit",
    )
    payload = agent._image_edit_payload(request)
    assert "semantic_operation" not in payload
    assert payload["source_path"] == str(sources[0])
    assert "source_paths" not in payload
    assert service.Edit(**payload).semantic_operation == "edit"
