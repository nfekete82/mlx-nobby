import json
from pathlib import Path
import sys

import pytest

import image_providers as providers
import mflux_capabilities as capabilities
import image_service as service


FLAGS = '--model --base-model --prompt --width --height --steps --guidance --seed --output --quantize --image-paths --lora-paths --lora-scales --mlx-cache-limit-gb --low-ram'.split()


def cli(tmp_path, monkeypatch, *, missing=(), telemetry=False):
    flags = [f for f in FLAGS if f not in missing] + (['--json-events'] if telemetry else [])
    executable = tmp_path / 'mflux-generate-qwen-edit'
    executable.write_text(f'''#!{sys.executable}
import argparse, sys
from PIL import Image
p=argparse.ArgumentParser()
for flag in {flags!r}:
    p.add_argument(flag, action='store_true' if flag in ('--json-events','--low-ram') else 'store')
if '--help' in sys.argv:
    with open({str(tmp_path/'probes')!r}, 'a') as log: log.write('probe\\n')
a=p.parse_args()
Image.new('RGB', (int(a.width), int(a.height))).save(a.output)
''')
    executable.chmod(0o755)
    monkeypatch.setattr(providers, 'MFLUX_BIN', tmp_path)
    capabilities.probe_mflux_cli.cache_clear()
    model_root = tmp_path / 'model'; model_root.mkdir()
    (model_root / 'weights.safetensors').touch()
    monkeypatch.setattr(providers, 'model_directory', lambda _: model_root)
    return executable


def model(family='qwen-image-edit'):
    return {'id':'image', 'provider':'mflux', 'model_family':family, 'base_model':family,
            'quantization':'none','quantize_on_load':False,'loras':[]}


def test_probe_is_cached_and_optional_telemetry_does_not_break_generation(tmp_path, monkeypatch):
    executable = cli(tmp_path, monkeypatch)
    found = capabilities.probe_mflux_cli(str(executable))
    assert found['available'] and '--json-events' not in found['supported_flags']
    events = []
    output = tmp_path/'keyframe.png'
    providers.run_provider(model(), {'source_path':str(tmp_path/'source.png'), 'prompt':'Office',
        'width':64,'height':64,'steps':1,'guidance':3.5,'seed':1}, output, progress_callback=events.append)
    assert output.is_file()
    assert events == [{'phase':'generating'}]
    assert (tmp_path/'probes').read_text().splitlines() == ['probe']


def test_edit_missing_required_argument_is_unavailable_before_spawn(tmp_path, monkeypatch):
    cli(tmp_path, monkeypatch, missing={'--image-paths'})
    ready, reason = providers.availability(model())
    assert not ready and '--image-paths' in reason
    with pytest.raises(providers.ProviderFailure):
        providers.mflux_command(model(), {}, tmp_path/'output.png')


@pytest.mark.parametrize('family', ['flux1','flux2-klein','qwen-image','z-image','z-image-turbo','qwen-image-edit'])
def test_family_contracts_use_only_supported_flags(family, tmp_path, monkeypatch):
    executable = cli(tmp_path, monkeypatch)
    flags = capabilities.probe_mflux_cli(str(executable))['supported_flags']
    monkeypatch.setattr(capabilities, 'probe_mflux_cli', lambda _: {'available':True,'supported_flags':flags,'error':None})
    monkeypatch.setattr(providers, 'probe_mflux_cli', capabilities.probe_mflux_cli)
    command = providers.mflux_command(model(family), {'prompt':'Office','source_path':'source.png',
        'width':64,'height':64,'steps':1,'guidance':3.5,'seed':1}, tmp_path/'output.png')
    assert {value.split('=',1)[0] for value in command if value.startswith('--')} <= flags
    assert '--canvas-policy' not in command and '--json-events' not in command
    if family=='qwen-image-edit': assert '--image-paths' in command
    else: assert '--base-model' in command


def test_auto_generation_skips_incompatible_models_and_refuses_unavailable_default(monkeypatch):
    bad=model();bad.update(id='bad',enabled=True,capabilities=['text_to_image'])
    good=bad | {'id':'good'}
    monkeypatch.setattr(service.registry, 'load_registry', lambda:{'models':[bad,good],'default_model':'bad'})
    monkeypatch.setattr(service, 'availability', lambda m:(m['id']=='good','reason'))
    assert service._auto_generation_model('Office')['id']=='good'
    monkeypatch.setattr(service, 'availability', lambda m:(False,'incompatible'))
    with pytest.raises(service.HTTPException, match='kompatibler'):
        service._auto_generation_model('Office')

@pytest.mark.parametrize('family,missing', [('flux1','--base-model'),('qwen-image','--guidance'),('z-image-turbo','--width')])
def test_generate_family_missing_required_flag_fails_preflight(family, missing, tmp_path, monkeypatch):
    executable=cli(tmp_path,monkeypatch,missing={missing})
    flags=capabilities.probe_mflux_cli(str(executable))['supported_flags']
    monkeypatch.setattr(capabilities,'probe_mflux_cli',lambda _: {'available':True,'supported_flags':flags,'error':None})
    ready,reason=capabilities.mflux_contract(model(family),executable)
    assert not ready and missing in reason


def test_actual_pipeline_router_also_refuses_incompatible_default(monkeypatch):
    # Importing the deployed extension patches the core service globally.
    # Restore those extension points after this isolated router test.
    monkeypatch.setattr(service, '_generation_model', service._generation_model)
    monkeypatch.setattr(service, '_generate_result', service._generate_result)
    import image_service_pipeline as pipeline
    bad=model('z-image-turbo') | {'id':'bad','enabled':True,'capabilities':['text_to_image']}
    monkeypatch.setattr(service.registry,'load_registry',lambda: {'models':[bad],'default_model':'bad'})
    monkeypatch.setattr(service,'availability',lambda _: (False,'incompatible'))
    with pytest.raises(service.HTTPException,match='kompatibler'):
        pipeline._route_generation_model('auto','Office')


def test_quantized_qwen_vision_weights_are_unavailable_before_runtime(tmp_path,monkeypatch):
    import struct
    cli(tmp_path,monkeypatch)
    component=tmp_path/'model/text_encoder';component.mkdir()
    header=json.dumps({'visual.blocks.0.attn.qkv.weight':{'dtype':'U32','shape':[3840,320],'data_offsets':[0,0]},
                       'visual.blocks.0.attn.qkv.scales':{'dtype':'BF16','shape':[3840,20],'data_offsets':[0,0]}}).encode()
    (component/'0.safetensors').write_bytes(struct.pack('<Q',len(header))+header)
    ready,reason=providers.availability(model())
    assert not ready and 'unquantisiert' in reason
    header=json.dumps({'visual.blocks.0.attn.qkv.weight':{'dtype':'BF16','shape':[3840,1280],'data_offsets':[0,0]}}).encode()
    (component/'0.safetensors').write_bytes(struct.pack('<Q',len(header))+header)
    assert providers.availability(model())[0]


def test_version_is_read_from_executable_environment(tmp_path):
    executable = tmp_path / 'env/bin/mflux-generate'
    executable.parent.mkdir(parents=True)
    executable.write_text(f'#!{sys.executable}\nprint("  --model MODEL")\n')
    executable.chmod(0o755)
    metadata = tmp_path / 'env/lib/python3.13/site-packages/mflux-0.20.0.dist-info/METADATA'
    metadata.parent.mkdir(parents=True)
    metadata.write_text('Name: mflux\nVersion: 0.20.0\n')
    found = capabilities.probe_mflux_cli(str(executable))
    assert found['version'] == '0.20.0'
    assert found['supported_flags'] == {'--model'}


def test_models_expose_serializable_cli_contract(tmp_path, monkeypatch):
    executable = cli(tmp_path, monkeypatch)
    monkeypatch.setattr(capabilities, '_version', lambda _: '0.20.0')
    from fastapi.testclient import TestClient
    monkeypatch.setattr(service.registry, 'load_registry', lambda: {'models': [model()]})
    response = TestClient(service.app, base_url="http://localhost").get('/models')
    assert response.status_code == 200
    info = response.json()['models'][0]
    assert info['available'] is True
    assert info['cli_capabilities']['version'] == '0.20.0'
    assert '--image-paths' in info['cli_capabilities']['supported_flags']
    assert info['cli_capabilities']['available'] is True
    assert executable.is_file()


@pytest.mark.parametrize('header', [b'[]', b'null', b'{"broken":'])
def test_malformed_qwen_headers_are_unavailable(tmp_path, monkeypatch, header):
    import struct
    cli(tmp_path, monkeypatch)
    component = tmp_path / 'model/text_encoder'
    component.mkdir()
    (component / '0.safetensors').write_bytes(struct.pack('<Q', len(header)) + header)
    ready, reason = providers.availability(model())
    assert not ready and 'ungültige' in reason


def test_advertised_optional_telemetry_is_supported(tmp_path, monkeypatch):
    cli(tmp_path, monkeypatch, telemetry=True)
    output = tmp_path / 'output.png'
    providers.run_provider(model(), {'source_path': 'source.png', 'prompt': 'Office',
        'width': 64, 'height': 64, 'steps': 1, 'guidance': 3.5, 'seed': 1},
        output, progress_callback=lambda event: None)
    assert output.is_file()


@pytest.mark.parametrize('exit_code,message,code', [
    (2, 'unrecognized arguments: --unexpected private-prompt /private/secret', 'IMAGE_PROVIDER_INCOMPATIBLE'),
    (1, 'Traceback private-prompt /private/secret', 'IMAGE_PROVIDER_FAILED'),
])
def test_process_failures_keep_private_output_out_of_diagnosis(tmp_path, monkeypatch, exit_code, message, code):
    executable = cli(tmp_path, monkeypatch)
    script = executable.read_text().replace(
        'Image.new(\'RGB\', (int(a.width), int(a.height))).save(a.output)',
        f'sys.stderr.write({message!r}); sys.exit({exit_code})')
    executable.write_text(script)
    output = tmp_path / 'output.png'
    with pytest.raises(providers.ProviderFailure) as caught:
        providers.run_provider(model(), {'source_path': 'source.png', 'prompt': 'Office',
            'width': 64, 'height': 64, 'steps': 1, 'guidance': 3.5, 'seed': 1}, output)
    diagnosis = caught.value.diagnosis
    assert diagnosis['error_code'] == code
    assert diagnosis['error_provider'] == 'mflux' and diagnosis['error_model'] == 'image'
    assert f'Exit {exit_code}' in diagnosis['error_detail_safe']
    assert 'private-prompt' not in json.dumps(diagnosis)
    assert '/private/secret' not in str(caught.value)
    assert output.with_suffix('.provider.log').read_text() == message
    assert output.with_suffix('.provider.log').stat().st_mode & 0o777 == 0o600


def test_image_job_preserves_structured_provider_failure(monkeypatch):
    import threading
    failure = providers.ProviderFailure('Provider incompatible', error_code='IMAGE_PROVIDER_INCOMPATIBLE',
        provider='mflux', model='image', detail='Missing --image-paths')
    def generate(*args, **kwargs):
        raise failure
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(service, '_lock', lock)
    monkeypatch.setattr(service, '_jobs', {'job': {'id': 'job', 'status': 'queued',
        '_cancel_event': threading.Event()}})
    monkeypatch.setattr(service, '_active_job_id', 'job')
    monkeypatch.setattr(service, '_generate_result', generate)
    from contextlib import nullcontext
    monkeypatch.setattr(service.runtime_coordinator, 'image_runtime', lambda _: nullcontext())
    service._run_image_job('job', 'generate', service.Generate(prompt='Office'))
    result = service.image_job('job')
    assert result['status'] == 'failed'
    assert {key: result[key] for key in failure.diagnosis} == failure.diagnosis
    assert not lock.locked()
