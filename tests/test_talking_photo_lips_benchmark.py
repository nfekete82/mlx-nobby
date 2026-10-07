import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/benchmark-talking-photo-lips.py'
spec = importlib.util.spec_from_file_location('lips_benchmark', SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class FrozenLipsBenchmarkTests(unittest.TestCase):
    def test_direct_command_uses_exact_frozen_audio_and_only_requested_seed_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'conditioning.wav').write_bytes(b'existing WAV bytes')
            (root/'image.png').write_bytes(b'existing image bytes')
            manifest = dict(model='/model', hashes={name:benchmark.digest(root/name)
                for name in ['conditioning.wav','image.png']})
            baseline = dict(seed=42, fps=24, frames=81, stage1_steps=15,stage2_steps=3,cfg_scale=3.,stg_scale=1.)
            original = benchmark.command(root,root/'render',baseline,manifest)
            variant = benchmark.command(root,root/'render',dict(baseline,seed=123),manifest)
            self.assertEqual(original[original.index('--audio')+1],str(root/'conditioning.wav'))
            differences = [(a,b) for a,b in zip(original,variant) if a!=b]
            self.assertEqual(differences,[('42','123')])
            self.assertEqual((root/'conditioning.wav').read_bytes(),b'existing WAV bytes')
            (root/'conditioning.wav').write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError,'Frozen input changed'):
                benchmark.command(root,root/'render',baseline,manifest)

    def test_completed_render_cannot_be_reused_with_different_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); folder=root/'seed-42'; folder.mkdir()
            (folder/'parameters.json').write_text(json.dumps(dict(parameters={'seed':42},status='completed')))
            with self.assertRaisesRegex(ValueError,'different experiment'):
                benchmark.run(root,'seed-42',{'seed':123},{})

    def test_required_seeds_present_without_duplicates(self):
        self.assertEqual(benchmark.SEEDS,[42,123,256,512,1024,1337,2026,4096,12345,54321])
        self.assertEqual(len(set(benchmark.SEEDS)),10)

    def test_parameter_phase_requires_completed_seed_sweep(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'selection.json').write_text(json.dumps({'best_seed':123}))
            with self.assertRaisesRegex(ValueError,'entire seed sweep'):
                benchmark.selected_seed(root)
            for seed in benchmark.SEEDS:
                folder=root/f'seed-{seed}';folder.mkdir()
                (folder/'parameters.json').write_text(json.dumps({'status':'completed'}))
            self.assertEqual(benchmark.selected_seed(root),123)


if __name__ == '__main__':
    unittest.main()
