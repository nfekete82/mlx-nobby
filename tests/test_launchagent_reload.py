"""No real launchctl calls: model async unload and transactional recovery."""
import importlib.util
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launchagent_reload', Path(__file__).resolve().parents[1] / 'scripts/reload-launchagent.py')
reload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reload)


class LaunchAgentReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / 'video.plist'
        self.candidate = Path(self.tmp.name) / 'candidate.plist'
        self.old = plistlib.dumps({'Label': 'de.fixture.video', 'EnvironmentVariables': {'ADAPTER': 'baseline', 'STRENGTH': '1.0'}})
        self.new = plistlib.dumps({'Label': 'de.fixture.video', 'EnvironmentVariables': {'ADAPTER': 'candidate', 'STRENGTH': '1.0'}})
        self.target.write_bytes(self.old)
        self.candidate.write_bytes(self.new)
        self.state = 'loaded'
        self.pending = 2
        self.calls = []
        self.fail_bootout = False
        self.fail_bootstrap = False
        self.foreign = False
        self.foreign_config = False
        self.bootstrap_configs = []

    def launchctl(self, command, **kwargs):
        self.calls.append(command[1:])
        action = command[1]
        if action == 'print':
            if self.state == 'unloading':
                if self.pending:
                    self.pending -= 1
                else:
                    self.state = 'absent'
            if self.state == 'absent':
                return subprocess.CompletedProcess(command, 113, '', 'Could not find service')
            path = '/foreign/video.plist' if self.foreign else str(self.target)
            return subprocess.CompletedProcess(command, 0, f'path = {path}\n', '')
        if action == 'bootout':
            if self.fail_bootout:
                return subprocess.CompletedProcess(command, 5, '', 'synthetic bootout failure')
            self.state = 'unloading'
            if self.foreign_config:
                self.target.write_bytes(b'foreign modification')
            return subprocess.CompletedProcess(command, 0, '', '')
        if action == 'bootstrap':
            self.assertEqual(self.state, 'absent', 'bootstrap raced asynchronous bootout')
            self.bootstrap_configs.append(self.target.read_bytes())
            if self.fail_bootstrap:
                self.fail_bootstrap = False
                return subprocess.CompletedProcess(command, 5, '', 'synthetic bootstrap failure')
            self.state = 'loaded'
            return subprocess.CompletedProcess(command, 0, '', '')
        self.fail('Unexpected launchctl action')

    def install(self):
        with patch.object(reload.subprocess, 'run', side_effect=self.launchctl), patch.object(reload.time, 'sleep'):
            return reload.install('gui/1000', 'de.fixture.video', self.candidate, self.target)

    def test_unchanged_has_no_launchctl_calls(self):
        self.candidate.write_bytes(self.old)
        self.assertFalse(self.install())
        self.assertEqual(self.calls, [])

    def test_changed_waits_until_unloaded_and_preserves_environment(self):
        self.assertTrue(self.install())
        self.assertEqual(self.state, 'loaded')
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.bootstrap_configs, [self.new])
        self.assertEqual(plistlib.loads(self.target.read_bytes())['EnvironmentVariables'], {'ADAPTER': 'candidate', 'STRENGTH': '1.0'})
        self.assertEqual(list(self.target.parent.glob('*.restore-*')), [])

    def test_bootout_failure_does_not_publish_candidate(self):
        self.fail_bootout = True
        with self.assertRaisesRegex(reload.ReloadError, 'bootout failed'):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.state, 'loaded')
        self.assertEqual(self.bootstrap_configs, [])

    def test_bootstrap_failure_restores_previous_config_and_service(self):
        self.fail_bootstrap = True
        with self.assertRaisesRegex(reload.ReloadError, 'previous configuration restored and loaded'):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.state, 'loaded')
        self.assertEqual(self.bootstrap_configs, [self.new, self.old])

    def test_foreign_service_path_fails_closed(self):
        self.foreign = True
        with self.assertRaisesRegex(reload.ReloadError, 'Unexpected loaded service path'):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(len(self.calls), 1)

    def test_foreign_config_change_is_preserved(self):
        self.foreign_config = True
        with self.assertRaisesRegex(reload.ReloadError, 'configuration changed'):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'foreign modification')
        self.assertEqual(self.bootstrap_configs, [])

    def test_unload_timeout_is_bounded_without_bootstrap_retry(self):
        with patch.object(reload.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(reload.ReloadError, 'Timed out'):
                self.install()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.bootstrap_configs, [])

    def test_unloaded_service_is_not_started_by_reinstallation(self):
        self.state = 'absent'
        self.assertTrue(self.install())
        self.assertEqual(self.state, 'absent')
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.bootstrap_configs, [])
