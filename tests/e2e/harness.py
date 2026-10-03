"""Deterministic downstream Agent contract; never imports inference services."""
import asyncio
import io
import json
import math
import struct
import threading
import time
import wave

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from PIL import Image


def audio_fixture():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', int(1200 * math.sin(i * math.tau * 440 / 8000)))
                                   for i in range(8000)))
    return output.getvalue()


def image_fixture():
    output = io.BytesIO()
    Image.new('RGB', (32, 24), 'red').save(output, format='PNG')
    return output.getvalue()


class AgentFixture:
    def __init__(self):
        self.app = FastAPI()
        self.reset()
        self.app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])(self.respond)

    def reset(self):
        self.calls = []
        self.chats = {}
        self.jobs = {}
        self.groups = {}
        self.uncensored = False
        self.hold_jobs = False
        self.speech_mode = 'normal'
        self.speech_gate = threading.Event()
        self.stream_gate = threading.Event()
        self.stream_gate.set()
        self.model_system_gate = threading.Event()
        self.model_system_gate.set()
        self.model_system_entered = threading.Event()
        self.model_pid = 1234
        self.answer = 'Acceptance streaming complete.'
        self.terminals = 0

    def count(self, path, method=None):
        return sum(p == path and (method is None or m == method) for m, p, _ in self.calls)

    def result(self, job):
        kind = job['kind']
        status = job['status']
        artifact = {f'{kind}_id': job['id'], 'artifact_id': job['id'], 'generation_job_id': job['id'],
                    'prompt': job['prompt'], 'width': 32, 'height': 24,
                    'duration': 1, 'model': 'Fixture', 'profile': job.get('profile', 'standard')}
        return {'tool': kind + '_generate', 'status': status, 'data': {'job': dict(job)},
                'artifacts': [artifact] if status == 'completed' else []}

    async def respond(self, request: Request, path: str):
        path = '/' + path
        payload = await request.json() if request.method in ('POST', 'PUT') and await request.body() else {}
        self.calls.append((request.method, path, payload))
        if path == '/api/runtime/chat/stream':
            gate, answer = self.stream_gate, self.answer
            async def stream():
                yield 'event: token\ndata: {"type":"content","text":"Acceptance streaming"}\n\n'
                while not gate.is_set():
                    await asyncio.sleep(.02)
                await asyncio.sleep(.15)
                yield 'event: token\ndata: ' + json.dumps({'type': 'content', 'text': answer.removeprefix('Acceptance streaming')}) + '\n\n'
                yield 'event: metrics\ndata: {"model_calls_in_turn":1}\n\n'
                self.terminals += 1
                yield 'event: done\ndata: {}\n\n'
            return StreamingResponse(stream(), media_type='text/event-stream')
        if path == '/api/mlx/audio/speech':
            gate, mode = self.speech_gate, self.speech_mode
            while not gate.is_set():
                await asyncio.sleep(.02)
            if mode == 'http':
                return JSONResponse({'detail': 'Fixture speech unavailable'}, status_code=503)
            return Response(b'invalid' if mode == 'invalid' else audio_fixture(), media_type='audio/wav')
        if path.startswith('/api/images/'):
            return Response(image_fixture(), media_type='image/png')
        if path.startswith('/api/videos/'):
            # CI controls the media layer; no codec/FFmpeg dependency or committed MP4.
            return Response(b'fixture-video', media_type='video/mp4')
        if path == '/api/chat/actions/route':
            target = 'video' if 'ball' in payload.get('prompt', '').lower() else 'image' if 'mug' in payload.get('prompt', '').lower() else 'chat'
            return {'target': target, 'intent': target + '_generate' if target != 'chat' else 'chat'}
        if path == '/api/chat/actions':
            kind = payload['resolved_target']
            if kind == 'chat':
                return {'tool': 'normal_chat', 'status': 'completed', 'data': {}}
            job_id = format(len(self.jobs) + 1, '024x')
            job = {'id': job_id, 'kind': kind, 'prompt': payload['prompt'], 'status': 'queued',
                   'phase': 'queued', 'progress': 0, 'polls': 0, 'created_at': time.time(),
                   'profile': (payload.get('video_options') or {}).get('profile', 'standard')}
            self.jobs[job_id] = job
            return self.result(job)
        if path == '/api/image/jobs/variants':
            base = self.jobs[payload['base_job_id']]
            group_id = 'f' * 24
            jobs = []
            for index in range(2 if payload['include_base'] else 1, payload['count'] + 1):
                job = dict(base, id=format(len(self.jobs) + 1, '024x'), status='completed',
                           phase='completed', variant_group_id=group_id,
                           variant_index=index, variant_count=payload['count'])
                self.jobs[job['id']] = job
                jobs.append(self.result(job))
            batch = {'variant_group_id': group_id, 'variant_count': payload['count'],
                     'base': self.result(base), 'jobs': jobs}
            self.groups[group_id] = batch
            return batch
        if path.startswith('/api/image/variant-groups/'):
            return self.groups[path.split('/')[4]]
        if path.startswith(('/api/image/jobs/', '/api/video/jobs/')):
            job_id = path.split('/')[4]
            job = self.jobs[job_id]
            if path.endswith('/cancel'):
                job.update(status='cancelled', phase='cancelled')
            elif job['status'] != 'cancelled':
                job['polls'] += 1
                stages = ['queued', 'loading', 'generating' if job['kind'] == 'video' else 'running', 'completed']
                index = min(job['polls'] - 1, 2 if self.hold_jobs else 3)
                job.update(status=stages[index], phase=stages[index], progress=index / 3,
                           current_step=index, total_steps=3)
            return self.result(job)
        if path == '/api/video/models':
            return {'models': [], 'preview_available': True, 'profiles': {'uncensored_available': self.uncensored}}
        if path == '/api/chats':
            return {'chats': list(self.chats.values()), 'deleted_ids': []}
        if path.startswith('/api/chats/'):
            chat_id = path.split('/')[3]
            if request.method == 'DELETE':
                self.chats.pop(chat_id, None)
                return {'ok': True}
            if request.method == 'PUT':
                self.chats[chat_id] = payload
            return {'chat': self.chats.get(chat_id, payload)}
        if path == '/api/system':
            self.model_system_entered.set()
            if not self.model_system_gate.is_set():
                await asyncio.to_thread(self.model_system_gate.wait)
        responses = {
            '/api/status': {'online': True, 'model': 'fixture/Qwen-4-bit', 'thinking': False},
            '/api/models': {'current': 'fixture/Qwen-4-bit', 'models': [{'alias': 'fixture', 'repo': 'fixture/Qwen-4-bit', 'name': 'Fixture Qwen', 'installed': True}]},
            '/api/model-roles': {'roles': {}, 'resolved': {}},
            '/api/system': {'mlx': {'memory_mb': 512, 'pid': self.model_pid, 'port': 8000, 'uptime_seconds': 60}, 'system': {'total_gb': 64, 'free_percent': 80}},
            '/api/cache': {'count': 0, 'total_size_bytes': 0, 'models': []},
            '/api/jobs': {'jobs': []}, '/api/batch': {'jobs': []},
            '/api/services/health': {'services': []},
            '/api/system/job-queue': {'jobs': [], 'waiting_count': 0, 'active_count': 0},
            '/api/image/models': {'models': [], 'effective_model': 'fixture', 'role': 'fixture'},
            '/api/image/health': {'available': True, 'preview_available': True},
            '/api/profile/context': {'context': ''}, '/api/profile': {'profile': {}},
            '/api/knowledge/status': {'sources': [], 'enabled': False},
            '/api/mlx/audio/voices': {'voices': ['Serena']},
            '/api/mlx/audio/voices/manage': {'voices': []},
            '/api/code/workspaces': {'workspaces': [], 'active': None},
            '/api/code/workspaces/active': {'workspace': None},
            '/api/notes': {'notes': [], 'folders': []},
            '/api/automations/notifications': {'notifications': []},
            '/api/model-scout/discover': {'candidates': [], 'profile': {}, 'sources': []},
            '/api/model-scout/benchmarks': {'benchmarks': []},
            '/api/image/prewarm': {'available': True},
            '/api/chat/route': {'intent': 'normal_chat'},
        }
        if path in responses:
            return responses[path]
        return JSONResponse({'detail': 'Unexpected fixture request: ' + path}, status_code=501)
