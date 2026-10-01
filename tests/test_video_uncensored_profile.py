import importlib.util
import os
import plistlib
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from pydantic import ValidationError

import video_profiles
import video_provider_dispatch as dispatch
import video_providers_mlx as mlx
import video_service
from agent import app as agent


class VideoUncensoredProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = Path(self.tmp.name).resolve() / 'adapter.safetensors'
        self.adapter.touch()
        self.environment = mock.patch.dict(os.environ, {
            'LTX_MLX_MODEL_DIR': self.tmp.name,
            'LTX_MLX_UNCENSORED_LORA': str(self.adapter),
            'LTX_MLX_UNCENSORED_LORA_STRENGTH': '0.75',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        core = types.ModuleType('mlx.core')
        core.load = mock.Mock(return_value={})
        self.loader = core.load
        modules = mock.patch.dict('sys.modules', {'mlx': types.ModuleType('mlx'), 'mlx.core': core})
        modules.start()
        self.addCleanup(modules.stop)
        upstream = types.ModuleType('ltx_pipelines_mlx.distilled')
        upstream.DistilledPipeline = mock.Mock()
        with mock.patch.dict('sys.modules', {
            'ltx_pipelines_mlx': types.ModuleType('ltx_pipelines_mlx'),
            'ltx_pipelines_mlx.distilled': upstream,
        }):
            spec = importlib.util.spec_from_file_location('test_mlx_worker', 'video_mlx_worker.py')
            self.worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.worker)
        self.pipe = mock.Mock()
        self.worker.DistilledPipeline.return_value = self.pipe
        self.calls = []

        def generate(**kwargs):
            self.calls.append((list(self.pipe._pending_loras), kwargs))
            Path(kwargs['output_path']).write_bytes(b'mp4')

        self.pipe.generate_and_save.side_effect = generate
        self.params = dict(prompt='A red ball rolls', output=str(Path(self.tmp.name) / 'out.mp4'),
                           width=1280, height=704, frames=121, fps=24, seed=42,
                           stage1_steps=8, stage2_steps=3)

    def test_worker_sequences_t2v_and_i2v(self):
        for image in (None, '/managed/first-frame.png'):
            for sequence in (('standard', 'uncensored', 'standard'),
                             ('uncensored', 'uncensored'), ('standard', 'standard')):
                for profile in sequence:
                    with self.subTest(image=image, profile=profile, sequence=sequence):
                        self.worker._generate(self.params | {'profile': profile, 'image': image,
                                                             'lora': '/client/adapter', 'strength': 99})
                        state, kwargs = self.calls[-1]
                        self.assertEqual(state, [(str(self.adapter), 0.75)] if profile == 'uncensored' else [])
                        if profile == 'uncensored':
                            self.loader.assert_called_with(str(self.adapter))
                        self.assertEqual(kwargs['image'], image)
                        self.assertEqual(kwargs['seed'], 42)
                        self.assertEqual(self.pipe._pending_loras, [])
        self.worker.DistilledPipeline.assert_called_once_with(
            model_dir=str(Path(self.tmp.name).resolve()), gemma_model_id=str(Path(self.tmp.name).resolve()),
            low_memory=True, low_ram_streaming=self.worker.LOW_RAM)

    def test_worker_default_ignores_configured_adapter(self):
        self.worker._generate(self.params)
        self.assertEqual(self.calls[-1][0], [])
        self.loader.assert_not_called()

    def test_invalid_adapter_preparation_stops_before_generation(self):
        self.loader.side_effect = RuntimeError('invalid adapter /private/internal/path')
        with self.assertRaisesRegex(ValueError, '^uncensored: Adapter konnte nicht vorbereitet werden$'):
            self.worker._generate(self.params | {'profile': 'uncensored'})
        self.pipe.generate_and_save.assert_not_called()
        self.assertIsNone(self.worker._PIPELINE)
        with mock.patch.object(mlx, 'PERSISTENT_WORKER', False), \
             mock.patch.object(mlx, 'availability', return_value=(True, 'ok')), \
             mock.patch.object(mlx.subprocess, 'run', side_effect=OSError('invalid adapter')) as prepare, \
             mock.patch.object(mlx, '_run_process') as generate:
            with self.assertRaisesRegex(ValueError, 'uncensored: Adapter konnte nicht vorbereitet werden'):
                mlx.generate({}, self.params | {'profile': 'uncensored'},
                             self.params['output'], cancel_event=threading.Event())
            prepare.assert_called_once()
            generate.assert_not_called()

    def test_worker_exception_and_cancellation_discard_loaded_pipeline(self):
        for error in (RuntimeError('generation failed'), KeyboardInterrupt()):
            self.worker._generate(self.params)
            def fail(**_kwargs):
                self.assertEqual(self.pipe._pending_loras, [(str(self.adapter), 0.75)])
                raise error

            self.pipe.generate_and_save.side_effect = fail
            with self.assertRaises(type(error)):
                self.worker._generate(self.params | {'profile': 'uncensored'})
            self.assertEqual(self.pipe._pending_loras, [])
            self.assertIsNone(self.worker._PIPELINE)
            self.assertFalse(self.worker._GENERATION_LOCK.locked())
            replacement = mock.Mock()
            def generate_standard(**kwargs):
                self.assertEqual(replacement._pending_loras, [])
                Path(kwargs['output_path']).touch()

            replacement.generate_and_save.side_effect = generate_standard
            self.worker.DistilledPipeline.return_value = replacement
            self.worker._generate(self.params)
            self.assertEqual(replacement._pending_loras, [])
            self.worker._PIPELINE = None
            self.worker.DistilledPipeline.return_value = self.pipe
            self.pipe.generate_and_save.side_effect = lambda **kw: Path(kw['output_path']).touch()

    def test_worker_validation_clears_previous_state_without_generation(self):
        self.worker._PIPELINE = self.pipe
        self.pipe._pending_loras = [('stale', 1.0)]
        with self.assertRaises(ValueError):
            self.worker._generate(self.params | {'profile': 'unknown'})
        self.assertEqual(self.pipe._pending_loras, [])
        self.pipe.generate_and_save.assert_not_called()
        self.assertFalse(self.worker._GENERATION_LOCK.locked())

    def test_configuration_errors_stop_before_runtime_or_generation(self):
        for config in ({'LTX_MLX_UNCENSORED_LORA': ''},
                       {'LTX_MLX_UNCENSORED_LORA': '/missing/adapter.safetensors'},
                       {'LTX_MLX_UNCENSORED_LORA': self.tmp.name},
                       *({'LTX_MLX_UNCENSORED_LORA_STRENGTH': value}
                         for value in ('invalid', 'nan', 'inf', '-inf'))):
            with self.subTest(config=config), mock.patch.dict(os.environ, config), \
                 mock.patch.object(mlx, '_acquire_runtime') as acquire, \
                 mock.patch.object(mlx, '_run_process') as run:
                with self.assertRaisesRegex(ValueError, 'uncensored: LTX_MLX_UNCENSORED_LORA'):
                    mlx.generate({}, self.params | {'profile': 'uncensored'},
                                 self.params['output'], cancel_event=threading.Event())
                acquire.assert_not_called()
                run.assert_not_called()
                with self.assertRaises(ValueError):
                    self.worker._generate(self.params | {'profile': 'uncensored'})
                self.pipe.generate_and_save.assert_not_called()
                self.assertEqual(video_profiles.request_loras(), [])

    def test_configuration_default_strength_and_normalized_path(self):
        os.environ.pop('LTX_MLX_UNCENSORED_LORA_STRENGTH')
        os.environ['LTX_MLX_UNCENSORED_LORA'] = str(self.adapter.parent / '.' / self.adapter.name)
        self.assertEqual(video_profiles.request_loras('uncensored'), [(str(self.adapter.resolve()), 1.0)])

    def test_cli_arguments_use_server_configuration_only(self):
        for image in (None, Path('/managed/first-frame.png')):
            standard = mlx._command({}, self.params, 'out.mp4', image=image)
            self.assertNotIn('--lora', standard)
            uncensored = mlx._command({}, self.params | {
                'profile': 'uncensored', 'lora': '/client/adapter', 'strength': 99,
            }, 'out.mp4', image=image)
            self.assertEqual(uncensored, standard + ['--lora', str(self.adapter), '0.75'])

    def test_service_and_agent_validate_and_forward_profiles(self):
        self.assertEqual(video_service.VideoPayload(prompt='A red ball rolls').profile, 'standard')
        for profile in ('standard', 'uncensored'):
            payload = video_service.VideoPayload(prompt='A red ball rolls', profile=profile)
            self.assertEqual(payload.model_dump()['profile'], profile)
            for operation in ('t2v', 'i2v'):
                request = agent.ChatActionRequest(prompt='A red ball rolls',
                    video_options={'profile': profile}, active_artifact_id='image-test')
                with mock.patch.object(agent, 'compile_video_prompt', side_effect=lambda value: value), \
                     mock.patch.object(agent, '_resolve_image_artifact_source', return_value=Path('/managed/image.png')):
                    forwarded = agent._video_payload(request, operation)
                self.assertEqual(forwarded['profile'], profile)
                if operation == 'i2v':
                    self.assertEqual(forwarded['first_frame'], '/managed/image.png')
        for options in ({'profile': 'unknown'}, {'profile': None},
                        {'profile': 'uncensored', 'lora': '/client/adapter'},
                        {'profile': 'uncensored', 'lora_path': '/client/adapter'},
                        {'profile': 'uncensored', 'strength': 99},
                        {'profile': 'uncensored', 'lora_strength': 99}):
            with self.subTest(options=options):
                with self.assertRaises(ValidationError):
                    video_service.VideoPayload(prompt='A red ball rolls', **options)
                with mock.patch.object(agent, 'compile_video_prompt', side_effect=lambda value: value):
                    with self.assertRaises(HTTPException) as error:
                        agent._video_payload(agent.ChatActionRequest(prompt='A red ball rolls', video_options=options), 't2v')
                    self.assertEqual(error.exception.status_code, 422)

    def test_warm_provider_forwards_profile_and_image_without_adapter_path(self):
        for image in (None, Path('/managed/first-frame.png')):
            for profile in ('standard', 'uncensored'):
                with mock.patch.object(mlx, '_acquire_runtime', return_value=(mock.Mock(), True)), \
                     mock.patch.object(mlx, 'unload'), \
                     mock.patch.object(mlx, '_json_request', return_value={'ok': True}) as request:
                    mlx._run_warm_worker({}, self.params | {'profile': profile}, 'out.mp4',
                                         image=image, cancel_event=threading.Event())
                payload = next(call.args[2] for call in request.call_args_list if call.args[0] == 'POST')
                self.assertEqual(payload['profile'], profile)
                self.assertEqual(payload['image'], str(image) if image else None)
                self.assertNotIn('lora', payload)
                self.assertNotIn('strength', payload)

    def test_uncensored_cannot_silently_use_other_provider(self):
        with mock.patch.object(dispatch.mps, 'generate') as generate:
            with self.assertRaisesRegex(ValueError, 'uncensored'):
                dispatch.generate({'provider': 'ltx-desktop-headless'}, {'profile': 'uncensored'}, 'out.mp4')
            generate.assert_not_called()

    def test_launchagent_configuration_escapes_environment_values(self):
        source = Path('scripts/install-launchd.sh').read_text()
        script = source.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        template = Path('launchd/templates/de.nobby.mlx-video.plist.template').read_bytes()
        target = Path(self.tmp.name) / 'video.plist'
        target.write_bytes(template)
        with mock.patch.dict(os.environ, {'LTX_MLX_UNCENSORED_LORA': '/configured/a&b<adapter>.safetensors'}), \
             mock.patch('sys.argv', ['renderer', str(target)]):
            exec(compile(script, 'install-launchd.sh', 'exec'), {})
        data = plistlib.loads(target.read_bytes())['EnvironmentVariables']
        self.assertEqual(data['LTX_MLX_UNCENSORED_LORA'], '/configured/a&b<adapter>.safetensors')
        self.assertEqual(data['LTX_MLX_UNCENSORED_LORA_STRENGTH'], '0.75')
