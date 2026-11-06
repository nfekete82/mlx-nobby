"""CPU contracts only: never load a checkpoint or start a production service."""
import copy
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

import image_registry as registry
import image_service as service
from agent import app as agent
from quality_profiles import resolve_image_profile, ULTRA_PLUS_DIMENSIONS


@pytest.fixture
def juggernaut(monkeypatch):
    model = next(m for m in registry.builtin_models() if m['id'] == 'juggernaut-xl')
    monkeypatch.setattr(service, '_generation_model', lambda *_: copy.deepcopy(model))
    return model


@pytest.mark.parametrize('ratio,expected', list(ULTRA_PLUS_DIMENSIONS.items()))
def test_native_plus_canvas_and_exact_ratio(juggernaut, ratio, expected):
    width, height = ratio[0] * 32, ratio[1] * 32
    # Input request minimum is 256, while preserving each ratio exactly.
    while min(width, height) < 256:
        width *= 2
        height *= 2
    request = service.Generate(prompt='Synthetic studio scene', quality='ultra_plus',
                               width=width, height=height, auto_size=True, seed=42)
    resolved = service._resolve_generation(request)
    params = resolved['params']
    assert (params['width'], params['height']) == expected
    assert params['width'] % 16 == params['height'] % 16 == 0
    assert params['width'] * ratio[1] == params['height'] * ratio[0]
    assert params['width'] * params['height'] <= 1664 ** 2
    assert params['steps'] == 40 and params['guidance'] == 4.0
    assert params['scheduler'] == 'dpmpp-2m-sde-karras'
    # Canonical regeneration keeps the actual native dimensions without auto_size.
    replay = service.Generate(**{**request.model_dump(), 'width': params['width'],
                                'height': params['height'], 'auto_size': False})
    assert service._resolve_generation(replay)['params'] == {**params, 'auto_size': False}


@pytest.mark.parametrize('input_size,expected', [
    ((432, 768), (864, 1536)),   # Portrait 9:16
    ((432, 576), (1152, 1536)),  # Portrait 3:4
    ((768, 432), (1536, 864)),   # Landscape 16:9
    ((576, 432), (1536, 1152)),  # Landscape 4:3
    ((512, 512), (1536, 1536)),  # Square
    ((832, 1216), (1056, 1536)), # Ragnarok portrait
])
def test_ultra_format_dimensions_match_picker_labels(juggernaut, input_size, expected):
    request = service.Generate(
        prompt='Synthetic format preview', model='juggernaut-xl',
        quality='ultra', width=input_size[0], height=input_size[1],
        auto_size=True, seed=7,
    )
    params = service._resolve_generation(request)['params']
    assert (params['width'], params['height']) == expected
    assert params['steps'] == 40
    assert params['width'] % 16 == params['height'] % 16 == 0


@pytest.mark.parametrize('quality,width,height', [('ultra', 1152, 1536), ('ultra_plus', 1248, 1664)])
def test_agent_transport_and_saved_metadata(juggernaut, monkeypatch, tmp_path, quality, width, height):
    monkeypatch.setattr(service, 'OUTPUT', tmp_path)
    monkeypatch.setattr(service.runtime_coordinator, 'ensure_model_load_allowed', lambda *_: None)
    monkeypatch.setattr(agent, 'translate_image_prompt_to_english', lambda text: text)
    action = agent.ChatActionRequest(prompt='Synthetic studio scene', quality=quality,
        image_options={'model': 'juggernaut-xl', 'width': width, 'height': height, 'auto_size': False})
    request = service.Generate(**agent._image_generate_payload(action))
    captured = []

    def provider(model, params, path, **_options):
        captured.append(copy.deepcopy(params))
        Image.new('RGB', (params['width'], params['height']), 'navy').save(path)
    monkeypatch.setattr(service, 'run_provider', provider)
    result = service._generate_result(request)
    assert result['quality'] == quality
    assert (result['width'], result['height']) == (width, height)
    assert result['steps'] == 40 and result['guidance'] == 4.0
    with Image.open(result['path']) as image:
        assert image.size == (width, height)
    monkeypatch.setattr(agent, 'IMAGE_DIRECTORY', tmp_path)
    artifact = agent._image_job_tool_result({'id': 'a' * 24, 'operation': 'generate',
        'status': 'completed', 'result': result})['artifacts'][0]
    assert (artifact['quality'], artifact['width'], artifact['height']) == (quality, width, height)
    assert len(captured) == 1
    assert (captured[0]['width'], captured[0]['height']) == (width, height)


@pytest.mark.parametrize('model_id,provider', [('cyberrealistic-pony-v18', 'sdxl'),
    ('other-sdxl', 'sdxl'), ('qwen', 'mflux'), ('juggernaut-xl', 'mflux')])
def test_plus_rejects_unapproved_model_or_provider(juggernaut, monkeypatch, model_id, provider):
    model = {**juggernaut, 'id': model_id, 'provider': provider}
    monkeypatch.setattr(service, '_generation_model', lambda *_: model)
    with pytest.raises(ValueError, match='nur für Juggernaut'):
        resolve_image_profile(model, 'ultra_plus')
    with pytest.raises(HTTPException) as exc:
        service._resolve_generation(service.Generate(prompt='Synthetic scene', quality='ultra_plus', auto_size=True))
    assert exc.value.status_code == 422


@pytest.mark.parametrize('quality,width,height,auto_size', [
    (None, 1248, 1664, False), ('quality', 1248, 1664, False),
    ('ultra', 1248, 1664, False), ('ultra_plus', 1824, 1824, False),
    ('ultra_plus', 1280, 1664, False), ('ultra_plus', 512, 768, True),
    ('ultra_plus', 1250, 1664, False),
])
def test_rejects_arbitrary_large_or_invalid_canvases(juggernaut, quality, width, height, auto_size):
    with pytest.raises(HTTPException) as exc:
        service._resolve_generation(service.Generate(prompt='Synthetic scene', quality=quality,
            width=width, height=height, auto_size=auto_size))
    assert exc.value.status_code == 422


def test_schema_envelope_is_bounded_and_edit_does_not_mislabel_plus():
    with pytest.raises(ValidationError):
        service.Generate(prompt='Synthetic scene', quality='ultra_plus', width=1840)
    # Img2img/reference still use their existing smaller safe working canvas.
    # Reject Ultra+ instead of promising native Plus then silently downsampling.
    with pytest.raises(ValidationError):
        service.Edit(prompt='Synthetic edit', source_path='/tmp/fixture.png', quality='ultra_plus')


@pytest.mark.parametrize('failure', [MemoryError('Synthetic memory shortage'), RuntimeError('Sicheres MPS-Speicherlimit erreicht; Bildauftrag beendet.')])
def test_memory_failure_is_single_attempt_without_quality_fallback(juggernaut, monkeypatch, tmp_path, failure):
    monkeypatch.setattr(service, 'OUTPUT', tmp_path)
    monkeypatch.setattr(service.runtime_coordinator, 'ensure_model_load_allowed', lambda *_: None)
    provider = Mock(side_effect=failure)
    monkeypatch.setattr(service, 'run_provider', provider)
    request = service.Generate(prompt='Synthetic scene', quality='ultra_plus',
        width=432, height=576, auto_size=True)
    with pytest.raises(type(failure), match=str(failure)):
        service._generate_result(request)
    assert provider.call_count == 1
    params = provider.call_args.args[1]
    assert (params['width'], params['height'], params['quality']) == (1248, 1664, 'ultra_plus')
    assert service._running is None
    assert not list(tmp_path.iterdir())


def test_memory_preflight_prevents_provider_load(juggernaut, monkeypatch, tmp_path):
    monkeypatch.setattr(service, 'OUTPUT', tmp_path)
    guard = Mock(side_effect=RuntimeError('Nicht genug freier Arbeitsspeicher'))
    monkeypatch.setattr(service.runtime_coordinator, 'ensure_model_load_allowed', guard)
    provider = Mock()
    monkeypatch.setattr(service, 'run_provider', provider)
    with pytest.raises(RuntimeError, match='Arbeitsspeicher'):
        service._generate_result(service.Generate(prompt='Synthetic scene', quality='ultra_plus',
            width=432, height=576, auto_size=True))
    provider.assert_not_called()
    guard.assert_called_once_with('image')


def test_cpu_memory_error_has_actionable_job_message():
    message = service._provider_failure(MemoryError())
    assert 'Arbeitsspeicher' in message and 'beendet' in message and 'Ultra' in message
