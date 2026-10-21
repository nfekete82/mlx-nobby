"""Opt-in model idle controller around the real MLX-VLM ASGI app.

Only enabled with MLX_CHAT_LIFECYCLE=1 in scripts/mlx-server-start.
Preserves original MLX-VLM CLI arguments via model_lifecycle_launcher.
"""
import asyncio
import fcntl
import json
import logging
import os
from pathlib import Path
import time

from mlx_vlm.server.app import app as mlx_app
from model_asgi_barrier import ASGIModelBarrier
from model_idle_policy import IdleState, evaluate_idle_unload

LOG = logging.getLogger('mlx-nobby.lifecycle')


class LifecycleASGI(ASGIModelBarrier):
    def __init__(self, app, *, role='chat', enabled=False, poll_seconds=30, lease_lock_path=None):
        super().__init__(app)
        if role not in {'chat', 'router'}:
            raise ValueError('Unknown lifecycle role')
        self.role = role
        self.enabled = enabled
        self.poll_seconds = poll_seconds
        self._task = None
        self.last_result = 'not_started'
        self.unload_count = 0
        self._halted = False
        self.lease_lock_path = lease_lock_path

    async def _call_upstream(self, method, route):
        """Invoke the *inner* ASGI app while this outer barrier is held.

        This is deliberately not a loopback HTTP call: it cannot deadlock
        waiting for the same unload barrier. The endpoint's normal FastAPI
        exception handling and response code remain in effect.
        """
        messages = []
        consumed = False

        async def receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type':'http.request','body':b'{}','more_body':False}
            # Defensive: an upstream route should not read another request
            # chunk; yield a disconnected client instead of spinning.
            return {'type':'http.disconnect'}

        async def send(message):
            messages.append(message)

        scope = {
            'type':'http', 'asgi':{'version':'3.0'},
            'http_version':'1.1', 'scheme':'http',
            'method':method, 'path':route, 'raw_path':route.encode(),
            'root_path':'', 'query_string':b'',
            'headers':[(b'content-type',b'application/json')],
            'client':('127.0.0.1',0), 'server':('127.0.0.1',0),
        }
        await self.app(scope, receive, send)
        status = next((m.get('status') for m in messages
                       if m['type']=='http.response.start'), 0)
        content = b''.join(m.get('body',b'') for m in messages
                           if m['type']=='http.response.body')
        if status != 200:
            raise RuntimeError(f'{method} {route}: HTTP {status}')
        return json.loads(content)

    async def _check_idle(self):
        """Unload only with both the HTTP barrier and the shared runtime lease.

        The flock is identical to runtime_coordinator.runtime_lease(). It
        excludes coordinated image, video, LTX, and chat jobs while unloading.
        It is nonblocking: a busy runtime simply skips this idle cycle.
        """
        if not self.enabled or self._halted:
            return
        threshold = 900 if self.role == 'chat' else 300
        if time.monotonic() - self.last_activity < threshold:
            return

        reserved = False
        lease_file = None
        lease_locked = False
        try:
            # Reserve the HTTP barrier atomically: no new inference can enter.
            async with self.condition:
                if self.active or self.pending or self.unloading:
                    self.last_result = 'requests_active_or_waiting'
                    return
                if time.monotonic() - self.last_activity < threshold:
                    return
                self.unloading = True
                reserved = True

            import runtime_coordinator
            lock_path = Path(self.lease_lock_path or runtime_coordinator.LOCK_PATH)
            lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            lease_file = lock_path.open('a+')
            try:
                fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lease_locked = True
            except BlockingIOError:
                self.last_result = 'runtime_lease_busy'
                return

            # Now protected against new coordinated runtime leases, and
            # against all HTTP inference handled by this ASGI instance.
            snapshot = runtime_coordinator.lease_state_snapshot()
            if snapshot.get('active') is not None or snapshot.get('waiting_count') != 0:
                self.last_result = 'runtime_lease_active_or_waiting'
                return

            health = await self._call_upstream('GET', '/health')
            loaded_models = health.get('loaded_models')
            if not isinstance(loaded_models, dict):
                raise RuntimeError('Unverifiable model health response')
            loaded = bool(loaded_models.get('text_generation') or health.get('loaded_model'))
            decision = evaluate_idle_unload(IdleState(
                role=self.role,
                now=time.monotonic(),
                last_activity=self.last_activity,
                loaded=loaded,
                idle_verified=True,
                lease_free=True,
                active_requests=self.active,
                pending_requests=self.pending,
                exclusive_session=False,
                server_identity_verified=(health.get('status') == 'healthy'),
            ))
            self.last_result = decision.reason
            if not decision.allowed:
                return

            # The joint ASGI + file locks remain held across the entire
            # actual MLX-VLM unload and post-unload verification.
            await self._call_upstream('POST', '/unload')
            after = await self._call_upstream('GET', '/health')
            if (not isinstance(after.get('loaded_models'), dict)
                    or after['loaded_models'].get('text_generation')
                    or after.get('loaded_model')):
                raise RuntimeError('Unload was not confirmed by health')
            self.unload_count += 1
            self.last_result = 'unloaded'
            LOG.info('Idle model unloaded safely: %s', self.role)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Fail closed: do not retry destructive operations on uncertainty.
            self._halted = True
            self.last_result = f'halted: {type(exc).__name__}: {exc}'
            LOG.exception('Lifecycle disabled after an unsafe/unknown state')
        finally:
            if lease_file is not None:
                try:
                    if lease_locked:
                        fcntl.flock(lease_file.fileno(), fcntl.LOCK_UN)
                finally:
                    lease_file.close()
            if reserved:
                async with self.condition:
                    self.unloading = False
                    self.condition.notify_all()

    async def _poll(self):
        while True:
            await asyncio.sleep(self.poll_seconds)
            await self._check_idle()

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'lifespan':
            async def watched_send(message):
                if message.get('type')=='lifespan.startup.complete' and self.enabled:
                    self.last_activity = time.monotonic()
                    self._task = asyncio.create_task(self._poll())
                if message.get('type') in ('lifespan.shutdown.complete',
                                            'lifespan.shutdown.failed'):
                    if self._task:
                        self._task.cancel()
                        try:
                            await self._task
                        except asyncio.CancelledError:
                            pass
                await send(message)
            return await super().__call__(scope, receive, watched_send)
        return await super().__call__(scope, receive, send)


app = LifecycleASGI(
    mlx_app,
    role=os.environ.get('MLX_LIFECYCLE_ROLE','chat'),
    enabled=os.environ.get('MLX_LIFECYCLE_ENABLE','0')=='1',
)
