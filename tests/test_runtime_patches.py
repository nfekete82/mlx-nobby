"""Network-free integration tests of the actual runtime patch helper and installer."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/apply-runtime-patches.py'
SETUP = ROOT / 'scripts/setup-ltx-video-mlx'
PIN = '1724ca673d59f023a8a95efee06e5d36d61c2765'


class RuntimePatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='runtime patches ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'runtime checkout'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Patch fixture')
        self.git('config', 'user.email', 'patch-fixture@example.invalid')
        (self.repo / 'sample.txt').write_text('original\n')
        (self.repo / 'other.txt').write_text('unchanged\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic upstream')
        self.pin = self.git('rev-parse', 'HEAD').stdout.strip()
        self.patch_root = self.root / 'patch root'
        self.series = self.patch_root / self.pin
        self.series.mkdir(parents=True)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True)

    def helper(self, *extra, pin=None):
        return subprocess.run([sys.executable, str(HELPER), str(self.repo),
                               pin or self.pin, str(self.patch_root), *extra],
                              capture_output=True, text=True)

    def patch(self, name='0001-change.patch', value='patched\n'):
        (self.repo / 'sample.txt').write_text(value)
        diff = self.git('diff', '--binary', '--full-index').stdout
        (self.series / name).write_text(diff)
        self.git('checkout', '--', 'sample.txt')
        return diff

    def snapshot(self):
        return (self.git('status', '--porcelain', '--untracked-files=all').stdout,
                {p.name: p.read_bytes() for p in self.repo.iterdir() if p.is_file()})

    def test_zero_patches(self):
        before = self.snapshot()
        self.assertEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_one_patch_and_second_run(self):
        self.patch()
        first = self.helper()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual((self.repo / 'sample.txt').read_text(), 'patched\n')
        before = self.snapshot()
        second = self.helper()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('already applied', second.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.git('diff', '--cached').stdout, '')

    def test_multiple_patches_are_ordered(self):
        first = self.patch(value='first\n')
        # Create a dependent second patch; keep the runtime at the original pin.
        second = first.replace('-original\n+first\n', '-first\n+second\n')
        (self.series / '0002-second.patch').write_text(second)
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / 'sample.txt').read_text(), 'second\n')
        self.assertEqual(self.helper().returncode, 0)

    def test_wrong_pin(self):
        wrong = 'a' * 40
        (self.patch_root / wrong).mkdir()
        before = self.snapshot()
        self.assertNotEqual(self.helper(pin=wrong).returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_non_applicable_later_patch_has_no_partial_application(self):
        self.patch()
        (self.series / '0002-broken.patch').write_text('not a patch\n')
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_unexpected_dirty_tree_is_preserved(self):
        self.patch()
        (self.repo / 'other.txt').write_text('foreign work\n')
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_applied_patch_plus_foreign_change_is_rejected(self):
        self.patch()
        self.assertEqual(self.helper().returncode, 0)
        (self.repo / 'foreign file').write_text('keep me')
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_partial_series_is_rejected(self):
        first = self.patch()
        (self.repo / 'other.txt').write_text('second change\n')
        (self.series / '0002-other.patch').write_text(self.git('diff').stdout)
        self.git('checkout', '--', 'other.txt')
        subprocess.run(['git', '-C', str(self.repo), 'apply', '-'], input=first,
                       text=True, check=True)
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_check_state_does_not_apply(self):
        self.patch()
        before = self.snapshot()
        self.assertEqual(self.helper('--check-state').returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_new_files_and_deletions_are_idempotent(self):
        (self.repo / 'new file.txt').write_text('new content\n')
        self.git('add', 'new file.txt')
        (self.repo / 'sample.txt').unlink()
        (self.series / '0001-files.patch').write_text(self.git('diff', 'HEAD').stdout)
        self.git('reset', '-q', 'HEAD', '--', 'new file.txt')
        (self.repo / 'new file.txt').unlink()
        self.git('checkout', '--', 'sample.txt')
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / 'sample.txt').exists())
        self.assertEqual((self.repo / 'new file.txt').read_text(), 'new content\n')
        self.assertEqual(self.helper().returncode, 0)

    def test_staged_changes_rejected(self):
        self.patch()
        self.assertEqual(self.helper().returncode, 0)
        self.git('add', 'sample.txt')
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_changed_patchset_does_not_trust_old_state(self):
        self.patch()
        self.assertEqual(self.helper().returncode, 0)
        (self.series / '0001-change.patch').write_text(
            (self.series / '0001-change.patch').read_text().replace('+patched', '+different'))
        before = self.snapshot()
        self.assertNotEqual(self.helper().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def installer_fixture(self):
        project = self.root / 'project space'
        (project / 'scripts').mkdir(parents=True)
        shutil.copyfile(HELPER, project / 'scripts/apply-runtime-patches.py')
        setup = project / 'scripts/setup-ltx-video-mlx'
        setup.write_text(SETUP.read_text().replace(PIN, self.pin))
        series = project / 'runtime-patches/ltx-2-mlx' / self.pin
        series.mkdir(parents=True)
        binaries = self.root / 'bin'
        binaries.mkdir()
        log = self.root / 'operations.log'
        real_git = shutil.which('git')
        scripts = {
            'uname': '#!/bin/bash\nif [ "$1" = -s ]; then echo Darwin; else echo arm64; fi\n',
            'git': '#!/bin/bash\nprintf "git %s\\n" "$*" >> "$PATCH_TEST_LOG"\n'
                   'case " $* " in *" fetch "*|*" remote set-url "*) exit 0;; esac\n'
                   f'exec "{real_git}" "$@"\n',
            'uv': '#!/bin/bash\nprintf "uv %s\\n" "$*" >> "$PATCH_TEST_LOG"\nexit 0\n',
        }
        for name, text in scripts.items():
            path = binaries / name
            path.write_text(text)
            path.chmod(0o755)
        # Ignore the fixture CLI locally without changing the committed upstream.
        (self.repo / '.git/info/exclude').write_text('.venv/\n')
        cli = self.repo / '.venv/bin/ltx-2-mlx'
        cli.parent.mkdir(parents=True)
        cli.write_text('#!/bin/bash\nexit 0\n')
        cli.chmod(0o755)
        model = self.root / 'models/ltx-2.5-mlx-q4'
        model.mkdir(parents=True)
        for name in ['embedded_config.json', 'text_encoder.safetensors', 'text_encoder_config.json']:
            (model / name).write_text('synthetic fixture')
        env = dict(os.environ, PATH=f'{binaries}:{os.environ["PATH"]}',
                   LTX_MLX_RUNTIME_ROOT=str(self.repo), LTX_MLX_MODEL_ROOT=str(model.parent),
                   PATCH_TEST_LOG=str(log))
        return setup, series, env, log

    def test_installer_runs_helper_before_sync_and_is_repeatable(self):
        self.patch()
        setup, series, env, log = self.installer_fixture()
        shutil.copyfile(self.series / '0001-change.patch', series / '0001-change.patch')
        for _ in range(2):
            result = subprocess.run(['bash', str(setup)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        operations = log.read_text()
        self.assertLess(operations.index(' apply --check'), operations.index('uv sync --frozen'))
        self.assertEqual((self.repo / 'sample.txt').read_text(), 'patched\n')
        source = SETUP.read_text()
        self.assertLess(source.index('checkout --quiet'), source.index('"$PATCH_ROOT"\n'))
        self.assertLess(source.index('"$PATCH_ROOT"\n'), source.index('uv sync --frozen'))
        self.assertIn('"$RUNTIME_ROOT" "$UPSTREAM_COMMIT" "$PATCH_ROOT"', source)

    def test_installer_patch_failure_stops_before_sync(self):
        setup, series, env, log = self.installer_fixture()
        (series / '0001-invalid.patch').write_text('invalid\n')
        before = self.snapshot()
        result = subprocess.run(['bash', str(setup)], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('uv ', log.read_text())
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
