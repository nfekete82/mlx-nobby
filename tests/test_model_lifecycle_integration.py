"""Real ASGI-inprocess lifecycle tests; no model weights needed."""
import asyncio
import fcntl
import tempfile
from pathlib import Path
import json
import time
import unittest
from unittest import mock
import sys
import types

# Agent venv does not ship the heavy mlx_vlm inference package.
# Stub only its import so lifecycle logic is exercised without model loads.
try:
    import mlx_vlm.server.app
except ModuleNotFoundError:
    sys.modules['mlx_vlm'] = types.ModuleType('mlx_vlm')
    sys.modules['mlx_vlm'].__path__ = []
    sys.modules['mlx_vlm.server'] = types.ModuleType('mlx_vlm.server')
    sys.modules['mlx_vlm.server'].__path__ = []
    fake = types.ModuleType('mlx_vlm.server.app')
    fake.app = object()
    sys.modules['mlx_vlm.server.app'] = fake

from model_lifecycle_asgi import LifecycleASGI


class LifecycleIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loaded = True
        self.inference_started = asyncio.Event()
        self.inference_finish = asyncio.Event()
        self.calls = []

        async def fake_app(scope, receive, send):
            route = scope.get('path')
            self.calls.append(route)
            if route == '/v1/chat/completions':
                self.inference_started.set()
                await self.inference_finish.wait()
                self.loaded = True
            elif route == '/unload':
                self.loaded = False
            status = {
                '/health': {'status':'healthy','loaded_models':
                            {'text_generation':{'model':'fixture'}} if self.loaded else {}},
                '/unload': {'status':'ok'},
            }.get(route, {'ok':True})
            raw = json.dumps(status).encode()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':raw,'more_body':False})

        self.lock_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.lock_dir.cleanup)
        self.lock_path = Path(self.lock_dir.name) / 'runtime.lock'
        self.barrier = LifecycleASGI(fake_app, role='chat', enabled=True,
                                     lease_lock_path=self.lock_path)

    async def test_real_idle_policy_unloads_once(self):
        self.barrier.last_activity -= 905
        with mock.patch('runtime_coordinator.lease_state_snapshot',
                        return_value={'active':None, 'waiting_count':0}):
            await self.barrier._check_idle()
        self.assertFalse(self.loaded)
        self.assertEqual(self.barrier.unload_count, 1)
        with mock.patch('runtime_coordinator.lease_state_snapshot',
                        return_value={'active':None, 'waiting_count':0}):
            await self.barrier._check_idle()
        self.assertEqual(self.barrier.unload_count, 1)

    async def test_live_request_protects_against_unload(self):
        async def receive():
            return {'type':'http.request','body':b'','more_body':False}
        async def send(message):
            return None
        task = asyncio.create_task(self.barrier(
            {'type':'http','method':'POST','path':'/v1/chat/completions'},
            receive, send,
        ))
        try:
            await asyncio.wait_for(self.inference_started.wait(), 2)
            self.barrier.last_activity -= 905
            await self.barrier._check_idle()
            self.assertTrue(self.loaded)
            self.assertNotIn('/unload', self.calls)
        finally:
            self.inference_finish.set()
            await asyncio.wait_for(task, 2)

    async def test_busy_runtime_file_lease_blocks_unload(self):
        self.barrier.last_activity -= 905
        with self.lock_path.open('a+') as other_job:
            fcntl.flock(other_job.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with mock.patch('runtime_coordinator.lease_state_snapshot',
                                return_value={'active': None, 'waiting_count': 0}):
                    await self.barrier._check_idle()
                self.assertTrue(self.loaded)
                self.assertNotIn('/unload', self.calls)
                self.assertEqual(self.barrier.last_result, 'runtime_lease_busy')
            finally:
                fcntl.flock(other_job.fileno(), fcntl.LOCK_UN)
