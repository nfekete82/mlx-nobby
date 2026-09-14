"""Destructive operations run only against isolated temporary models and stores."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from fastapi import HTTPException

# Import-time job recovery must never read/write the real user's history.
with tempfile.TemporaryDirectory() as import_home:
    with mock.patch.object(Path, 'home', return_value=Path(import_home)):
        from agent import app as agent
from agent import model_cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'Models'
        self.model = self.root / 'test-model'
        self.model.mkdir(parents=True)
        (self.model / 'config.json').write_text('{}')
        (self.model / 'weights.safetensors').write_bytes(b'test weights')
        self.aliases = self.base / 'aliases'
        self.aliases.write_text('# preserved comment\ntest=' + str(self.model) + '\nremote=owner/model\n')
        self.roles = self.base / 'roles.json'
        self.roles.write_text('{}')
        self.downloads = self.base / 'downloads.json'
        self.batch = self.base / 'batch' / 'jobs.json'
        self.batch.parent.mkdir()
        patches = [
            mock.patch.multiple(agent, MODELS=self.aliases, LOCAL_MODELS_ROOT=self.root,
                                MODEL_ROLES_FILE=self.roles, JOBS_FILE=self.downloads,
                                BATCH_DIRECTORY=self.batch.parent, BATCH_JOBS_FILE=self.batch,
                                JOBS={}, BATCH_WORKERS={}, MODEL_RUNTIME_LOCK=threading.RLock()),
            mock.patch.object(agent, 'load_config', return_value={'MODEL': '/other/active', 'PORT': '8000'}),
            mock.patch.object(agent, 'mlx_server_args', return_value=[]),
            mock.patch.object(agent, 'find_server_pid', return_value=None),
            mock.patch.object(agent.subprocess, 'run', side_effect=self.manager),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def manager(self, args, **kwargs):
        self.assertEqual(args[1], 'model')
        alias = args[3]
        if args[2] == 'remove':
            lines = self.aliases.read_text().splitlines()
            self.aliases.write_text('\n'.join(line for line in lines if not line.startswith(alias + '=')) + '\n')
        elif args[2] == 'add':
            self.aliases.write_text(self.aliases.read_text() + alias + '=' + args[4] + '\n')
        return mock.Mock(returncode=0, stdout='ok', stderr='')

    def assert_blocked(self, status, alias='test'):
        before = self.aliases.read_text()
        with self.assertRaises(HTTPException) as caught:
            agent.delete_local_model(alias)
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(self.aliases.read_text(), before)
        self.assertTrue((self.model / 'weights.safetensors').exists())

    def test_active_configured_model_cannot_be_deleted_even_if_offline(self):
        with mock.patch.object(agent, 'load_config', return_value={'MODEL': str(self.model)}):
            self.assert_blocked(409)

    def test_actual_running_model_cannot_be_deleted(self):
        with mock.patch.object(agent, 'mlx_server_args', return_value=['server', '--model', str(self.model)]):
            self.assert_blocked(409)

    def test_uninspectable_runtime_blocks_deletion(self):
        with mock.patch.object(agent, 'find_server_pid', return_value=123), mock.patch.object(
            agent, 'mlx_server_args', return_value=['server', '--port', '8000']
        ):
            self.assert_blocked(409)

    def test_download_destination_is_protected_after_alias_change(self):
        agent.JOBS['download'] = {'id': 'download', 'status': 'running', 'target': 'old-alias',
                                  'local_path': str(self.model / 'subfolder')}
        self.assert_blocked(409)

    def test_manager_success_without_alias_removal_preserves_files(self):
        with mock.patch.object(agent.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='ok')):
            self.assert_blocked(500)

    def test_unknown_and_remote_models_cannot_be_deleted(self):
        self.assert_blocked(404, 'unknown')
        self.assert_blocked(400, 'remote')

    def test_external_root_and_traversal_are_rejected(self):
        for path in [self.base, self.root, self.root / '..' / 'Models' / 'test-model']:
            with self.subTest(path=path):
                self.aliases.write_text('test=' + str(path) + '\n')
                self.assert_blocked(400 if '..' in path.parts else 403)

    def test_target_and_parent_symlinks_are_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.model, target_is_directory=True)
        parent_link = self.base / 'ModelsLink'
        parent_link.symlink_to(self.root, target_is_directory=True)
        self.aliases.write_text('test=' + str(link) + '\n')
        self.assert_blocked(403)
        with mock.patch.object(agent, 'LOCAL_MODELS_ROOT', parent_link):
            self.aliases.write_text('test=' + str(parent_link / 'test-model') + '\n')
            self.assert_blocked(403)

    def test_internal_symlink_does_not_delete_external_data(self):
        outside = self.base / 'outside'
        outside.mkdir()
        sentinel = outside / 'keep.txt'
        sentinel.write_text('keep')
        (self.model / 'external-link').symlink_to(outside, target_is_directory=True)
        agent.delete_local_model('test')
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_role_assignment_and_unreadable_roles_block_deletion(self):
        self.roles.write_text('{"vision":"test"}')
        self.assert_blocked(409)
        self.roles.write_text('broken json')
        self.assert_blocked(409)

    def test_shared_path_and_nested_alias_block_deletion(self):
        for path in [self.model, self.model / 'submodel']:
            self.aliases.write_text('test=' + str(self.model) + '\nother=' + str(path) + '\n')
            self.assert_blocked(409)

    def test_router_model_is_protected(self):
        with mock.patch.object(agent, 'ROUTER_MODEL', str(self.model)):
            self.assert_blocked(409)

    def test_active_download_blocks_deletion(self):
        for status in ['running', 'queued', 'detached']:
            agent.JOBS['download'] = {'id': 'download', 'target': 'test', 'status': status}
            self.assert_blocked(409)

    def test_runtime_lock_blocks_deletion(self):
        lock = mock.Mock()
        lock.acquire.return_value = False
        with mock.patch.object(agent, 'MODEL_RUNTIME_LOCK', lock):
            self.assert_blocked(409)
        lock.release.assert_not_called()

    def test_valid_local_model_and_alias_are_deleted(self):
        result = agent.delete_local_model('test')
        self.assertTrue(result['ok'])
        self.assertFalse(self.model.exists())
        self.assertEqual(self.aliases.read_text(), '# preserved comment\nremote=owner/model\n')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_manager_failure_preserves_model_and_alias(self):
        with mock.patch.object(agent.subprocess, 'run', return_value=mock.Mock(returncode=1, stdout='', stderr='failed')):
            self.assert_blocked(500)

    def test_deletion_failure_restores_alias_and_remaining_files(self):
        with mock.patch.object(model_cleanup.shutil, 'rmtree', side_effect=OSError('failure')) as remove:
            remove.avoids_symlink_attacks = True
            with self.assertRaises(HTTPException) as caught:
                agent.delete_local_model('test')
        self.assertEqual(caught.exception.status_code, 500)
        self.assertTrue(self.model.is_dir())
        self.assertIn('test=' + str(self.model), self.aliases.read_text())

    def seed_downloads(self):
        statuses = ['completed', 'failed', 'cancelled', 'interrupted', 'running', 'queued', 'detached', 'paused', 'active', 'unknown']
        agent.JOBS.update({status: {'id': status, 'status': status, 'target': 'test', 'pid': None} for status in statuses})
        agent.save_jobs()

    def test_completed_downloads_removed_running_preserved_and_model_untouched(self):
        self.seed_downloads()
        result = agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='completed'))
        self.assertEqual(result['removed'], 1)
        self.assertNotIn('completed', agent.JOBS)
        self.assertIn('running', agent.JOBS)
        self.assertTrue(self.model.exists())
        persisted = json.loads(self.downloads.read_text())['jobs']
        self.assertEqual({job['id'] for job in persisted}, set(agent.JOBS))

    def test_all_download_history_keeps_every_nonterminal_status(self):
        self.seed_downloads()
        result = agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='all'))
        self.assertEqual(result['removed'], 4)
        self.assertEqual(set(agent.JOBS), {'running', 'queued', 'detached', 'paused', 'active', 'unknown'})

    def test_failed_filter_and_live_process_are_protected(self):
        self.seed_downloads()
        agent.JOBS['completed']['pid'] = os.getpid()
        agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='failed'))
        self.assertNotIn('failed', agent.JOBS)
        agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='all'))
        self.assertIn('completed', agent.JOBS)

    def test_save_jobs_best_effort_swallows_persistence_failure(self):
        self.seed_downloads()

        with mock.patch.object(
            agent,
            'write_jobs_snapshot',
            side_effect=OSError('disk full'),
        ):
            agent.save_jobs()

    def test_save_jobs_strict_propagates_persistence_failure(self):
        self.seed_downloads()

        with mock.patch.object(
            agent,
            'write_jobs_snapshot',
            side_effect=OSError('disk full'),
        ):
            with self.assertRaisesRegex(OSError, 'disk full'):
                agent.save_jobs(strict=True)

    def test_failed_persistence_does_not_remove_in_memory_history(self):
        self.seed_downloads()
        before = self.downloads.read_text()
        with mock.patch.object(agent, 'write_jobs_snapshot', side_effect=OSError('disk full')):
            with self.assertRaises(HTTPException):
                agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='all'))
        self.assertIn('completed', agent.JOBS)
        self.assertEqual(self.downloads.read_text(), before)

    def seed_batch(self):
        statuses = ['completed', 'failed', 'cancelled', 'interrupted', 'running', 'queued', 'paused', 'active', 'unknown']
        jobs = {status: {'id': status, 'status': status, 'input_path': str(self.model / 'config.json')} for status in statuses}
        agent.save_batch_jobs(jobs)

    def test_completed_batch_jobs_can_be_removed_without_deleting_files(self):
        self.seed_batch()
        result = agent.cleanup_batch_history(agent.HistoryCleanupRequest(scope='completed'))
        self.assertEqual(result['removed'], 1)
        self.assertNotIn('completed', agent.load_batch_jobs())
        self.assertIn('running', agent.load_batch_jobs())
        self.assertTrue((self.model / 'config.json').exists())

    def test_all_batch_history_keeps_active_workers_and_nonterminal_states(self):
        self.seed_batch()
        agent.BATCH_WORKERS['cancelled'] = mock.Mock()
        agent.cleanup_batch_history(agent.HistoryCleanupRequest(scope='all'))
        self.assertEqual(set(agent.load_batch_jobs()), {'cancelled', 'running', 'queued', 'paused', 'active', 'unknown'})

    def test_corrupt_batch_store_is_not_overwritten(self):
        self.batch.write_text('{invalid')
        with self.assertRaises(HTTPException):
            agent.cleanup_batch_history(agent.HistoryCleanupRequest(scope='all'))
        self.assertEqual(self.batch.read_text(), '{invalid')

    def test_download_writer_does_not_resurrect_cleaned_history(self):
        self.seed_downloads()
        agent.cleanup_download_history(agent.HistoryCleanupRequest(scope='all'))
        agent.save_jobs()
        persisted = json.loads(self.downloads.read_text())['jobs']
        self.assertNotIn('completed', {job['id'] for job in persisted})

    def test_http_routes_validate_cleanup_scope_and_unknown_model(self):
        async def request(path, method, payload):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}
            async def send(message):
                messages.append(message)
            await agent.app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                             'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                             'query_string': b'', 'root_path': '', 'server': ('test', 80), 'client': ('test', 1),
                             'headers': [(b'host', b'localhost'),
                                       (b'content-type', b'application/json')]}, receive, send)
            return next(message['status'] for message in messages if message['type'] == 'http.response.start')
        for endpoint in ['/api/jobs/cleanup', '/api/batch/cleanup']:
            self.assertEqual(asyncio.run(request(endpoint, 'POST', {'scope': 'running'})), 422)
            self.assertEqual(asyncio.run(request(endpoint, 'POST', {'scope': 'completed'})), 200)
        self.assertEqual(asyncio.run(request('/api/models/unknown/local', 'DELETE', {})), 404)


if __name__ == '__main__':
    unittest.main()
