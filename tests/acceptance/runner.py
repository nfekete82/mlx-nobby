"""Opt-in Mac acceptance against installed services. No setup, downloads or model selection."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time
from urllib.parse import urlsplit
import uuid

import httpx
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {'completed', 'failed', 'cancelled'}


class Skip(RuntimeError):
    pass


def loopback_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'} or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError('Acceptance requires an HTTP loopback URL without credentials')
    return value.rstrip('/')


def cached_model(model, loaded=False):
    if loaded:
        return True
    path = Path(str(model)).expanduser()
    if path.is_dir():
        return any(path.glob('*.safetensors'))
    if '/' in str(model):
        snapshots = Path.home() / '.cache/huggingface/hub' / ('models--' + str(model).replace('/', '--')) / 'snapshots'
        return any(p.is_file() for p in snapshots.glob('*/*.safetensors'))
    return False


def inspect_image(data):
    assert len(data) > 100, 'Image is too small'
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        assert image.width > 0 and image.height > 0
        extrema = ImageStat.Stat(image.convert('RGB')).extrema
        assert any(high - low > 2 for low, high in extrema), 'Trivial uniform/blank image'
        return {'width': image.width, 'height': image.height, 'bytes': len(data), 'format': image.format}


def inspect_media(path, kind):
    if not shutil.which('ffprobe'):
        raise Skip('ffprobe is required for real audio/video validation')
    completed = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                '-of', 'json', str(path)], capture_output=True, text=True, timeout=20, check=True)
    probe = json.loads(completed.stdout)
    streams = [s for s in probe.get('streams', []) if s.get('codec_type') == kind]
    assert streams, f'No {kind} stream'
    duration = float(probe.get('format', {}).get('duration') or streams[0].get('duration') or 0)
    assert duration > 0, f'No {kind} duration'
    if kind == 'video':
        assert streams[0]['width'] > 0 and streams[0]['height'] > 0
        assert Fraction(streams[0].get('avg_frame_rate', '0/1')) > 0
    # Decode the complete short fixture; metadata alone cannot prove playable frames.
    if shutil.which('ffmpeg'):
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0' if kind == 'video' else '0:a:0',
                        '-f', 'null', '-'], capture_output=True, timeout=30, check=True)
    return {'duration': duration, 'streams': [{k: s[k] for k in
            ('codec_type', 'codec_name', 'width', 'height', 'avg_frame_rate', 'nb_frames') if k in s}
            for s in probe.get('streams', [])], 'bytes': path.stat().st_size}


def inspect_preview(artifact):
    assert artifact.get('quality') == 'preview' and artifact.get('resolution') == 'preview', 'Output is not a Preview'
    fps = float(artifact.get('fps') or 0)
    assert fps > 0, 'Preview has no FPS'
    # LTX includes the first frame: 2 * FPS + 1 frames, hence one-frame duration tolerance.
    assert 0 < float(artifact.get('duration') or 0) <= 2 + 1 / fps + .01, 'Preview exceeds the two-second frame budget'
    assert max(artifact.get('width', 0), artifact.get('height', 0)) <= 384, 'Preview exceeded low resolution'


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.run_id = 'acceptance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        self.chat_id = self.run_id
        self.root = ROOT / 'artifacts/acceptance' / self.run_id
        self.root.mkdir(parents=True)
        self.client = httpx.Client(base_url=args.url, timeout=20, trust_env=False)
        self.results, self.network, self.jobs, self.drafts = [], [], [], []
        self.chat = None
        self.before = {}
        self.probe_errors = {}
        self.browser = self.context = self.page = self.playwright = None
        self.console, self.errors = [], []
        self.started = time.monotonic()
        self.image_result = self.video_result = None
        self.timers = {'chat': args.chat_timeout, 'tts': args.tts_timeout,
                       'image': args.image_timeout, 'video': args.video_timeout}

    def request(self, method, path, payload=None, timeout=20, expected=(200,)):
        started = time.monotonic()
        response = self.client.request(method, path, json=payload, timeout=timeout)
        self.network.append({'method': method, 'path': path, 'status': response.status_code,
                             'seconds': round(time.monotonic() - started, 3)})
        assert response.status_code in expected, f'{method} {path}: HTTP {response.status_code}: {response.text[:500]}'
        return response

    def json(self, method, path, payload=None, **kwargs):
        return self.request(method, path, payload, **kwargs).json()

    def check(self, name, fn):
        started = time.monotonic()
        try:
            detail = fn() or {}
            status = 'PASS'
        except Skip as exc:
            status, detail = 'SKIP', {'reason': str(exc)}
        except Exception as exc:
            status, detail = 'FAIL', {'error': str(exc) or repr(exc)}
            if self.page:
                try:
                    if self.page.locator('.message.user').filter(has_text=self.run_id).count():
                        self.page.screenshot(path=str(self.root / (name.lower().replace(' ', '-') + '.png')), full_page=True)
                    self.context.tracing.stop(path=str(self.root / ('browser-failure-' + name.lower().replace(' ', '-') + '.zip')))
                except Exception as diagnostic_error:
                    detail['diagnostic_error'] = str(diagnostic_error)
                finally:
                    # Cleanup owns the context even if a crashed browser cannot save diagnostics.
                    if self.context:
                        try:
                            self.context.close()
                        except Exception:
                            pass
                    self.context = self.page = None
        self.results.append({'name': name, 'status': status, 'seconds': round(time.monotonic() - started, 2), 'detail': detail})
        print(f'{name:26} {status}', flush=True)
        if status != 'PASS':
            print('  ' + str(detail.get('error', detail.get('reason', ''))), flush=True)

    def preflight(self):
        assert platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Real acceptance requires Apple Silicon macOS'
        self.before['web'] = self.json('GET', '/api/health')
        self.before['chat'] = self.json('GET', '/api/mlx/status')
        roles = self.json('GET', '/api/mlx/model-roles')
        resolved_chat = roles.get('resolved', {}).get('chat')
        if self.before['chat'].get('online'):
            assert isinstance(resolved_chat, dict) and not resolved_chat.get('requires_switch'), 'Chat role selects a different model; acceptance will not switch it'
        self.before['services'] = self.json('GET', '/api/mlx/services/health')
        self.before['queue'] = self.json('GET', '/api/system/job-queue')
        assert not self.before['queue'].get('active_count') and not self.before['queue'].get('waiting_count'), 'Other media jobs are active; retry when the queue is idle'
        self.image_models = self.probe('image', lambda: self.json('GET', '/api/image/models'))
        self.video_models = self.probe('video', lambda: self.json('GET', '/api/mlx/video/models'))
        self.image_model = next((m for m in self.image_models.get('models', []) if m['id'] == self.image_models.get('effective_model')), None)
        self.video_model = next((m for m in self.video_models.get('models', []) if m['id'] == self.video_models.get('default_model')), None)
        # Read native health only; inference remains on the normal production web path.
        self.speech_health = self.probe('speech', lambda: self.native_json(self.args.speech_url + '/health'))
        self.before['image'] = self.probe('image', lambda: self.json('GET', '/api/image/health'))
        self.before['video'] = self.probe('video', lambda: self.native_json(self.args.video_url + '/health'))
        (self.root / 'state-before.json').write_text(json.dumps(self.before, indent=2))
        assert not self.before['image'].get('active_generation') and not self.before['video'].get('active_generation'), 'Native media service is busy'
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        return {'architecture': platform.machine(), 'chat_online': self.before['chat'].get('online'),
                'image_available': self.image_model.get('available') if self.image_model else False,
                'video_available': self.video_model.get('available') if self.video_model else False,
                'uncensored_available': self.video_models.get('profiles', {}).get('uncensored_available', False),
                'ffprobe': bool(shutil.which('ffprobe')), 'ffmpeg': bool(shutil.which('ffmpeg'))}

    def probe(self, kind, fn):
        try:
            return fn()
        except Exception as exc:
            advertised = {'image': 'Images', 'video': 'Video', 'speech': 'Speech'}[kind]
            expected = any(s.get('name') == advertised and s.get('online')
                           for s in self.before['services'].get('services', []))
            self.probe_errors[kind] = (expected, str(exc))
            return {}

    def readiness(self, kind):
        if kind in self.probe_errors:
            expected, error = self.probe_errors[kind]
            if expected:
                raise AssertionError(f'{kind} advertised online but preflight failed: {error}')
            raise Skip(f'{kind} service unavailable; no service started')
        if kind != 'image' and (not shutil.which('ffprobe') or not shutil.which('ffmpeg')):
            raise Skip('ffprobe/ffmpeg unavailable; no real media jobs started')

    def native_json(self, url):
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def chat_test(self):
        if not self.before['chat'].get('online'):
            raise Skip('No loaded chat runtime; acceptance never loads or selects one')
        payload = {'messages': [{'role': 'user', 'content': 'Antworte exakt mit: MLX_NOBBY_ACCEPTANCE_OK'}],
                   'system_prompt': 'Return only the requested marker.', 'temperature': 0, 'max_tokens': 64,
                   'trace_id': self.run_id}
        deadline = time.monotonic() + self.timers['chat']
        frames, text, done = [], '', False
        with self.client.stream('POST', '/api/chat/stream', json=payload, timeout=self.timers['chat']) as response:
            assert response.status_code == 200
            event = ''
            for line in response.iter_lines():
                assert time.monotonic() < deadline, 'Chat total timeout'
                frames.append(line)
                if line.startswith('event:'):
                    event = line[6:].strip()
                if line.startswith('data:'):
                    data = json.loads(line[5:])
                    assert not data.get('error'), data.get('error')
                    if data.get('type') != 'reasoning':
                        text += data.get('text', '')
                    done |= event == 'done'
        (self.root / 'chat.sse').write_text('\n'.join(frames))
        assert done and 'MLX_NOBBY_ACCEPTANCE_OK' in text, 'Missing marker or terminal done'
        return {'marker': True, 'terminal_done': done}

    def gateway(self):
        if not self.before['chat'].get('online'):
            raise Skip('No loaded chat runtime')
        before = {c['id'] for c in self.json('GET', '/api/mlx/chats')['chats']}
        models = self.json('GET', '/v1/models')['data']
        assert any(m['id'] == 'mlx-nobby/chat' for m in models)
        result = self.json('POST', '/v1/chat/completions', {'model': 'mlx-nobby/chat',
                           'messages': [{'role': 'user', 'content': 'Reply exactly: GATEWAY_OK'}],
                           'temperature': 0, 'max_tokens': 64}, timeout=self.timers['chat'])
        assert 'GATEWAY_OK' in result['choices'][0]['message']['content']
        assert result.get('usage', {}).get('total_tokens', 0) > 0
        after = {c['id'] for c in self.json('GET', '/api/mlx/chats')['chats']}
        assert before == after, 'Gateway persisted a chat (or concurrent user activity changed history)'
        return {'marker': True, 'usage': result['usage'], 'stateless': True}

    def own_chat(self, messages):
        now = int(time.time() * 1000)
        # Production history intentionally removes legacy chats without a user turn.
        messages = [{'role': 'user', 'content': self.run_id}] + messages
        candidate = dict(id=self.chat_id, title=self.run_id, created=now, updated=now, revision=0,
                         messages=messages, settings={'system_prompt': '', 'preset_id': 'general', 'temperature': 0, 'max_tokens': 64})
        result = self.json('PUT', '/api/mlx/chats/' + self.chat_id, candidate)
        self.chat = result['chat']
        assert self.chat['id'] == self.chat_id
        assert self.json('GET', '/api/mlx/chats/' + self.chat_id)['chat']['id'] == self.chat_id

    def speech_ready(self):
        self.readiness('speech')
        health = self.speech_health
        if not cached_model(health.get('tts_model', ''), health.get('tts_loaded', False)):
            raise Skip('TTS weights are not installed locally; no download attempted')

    def tts(self):
        self.speech_ready()
        voices = self.json('GET', '/api/mlx/audio/voices')['voices']
        assert any(v.get('id') == 'Serena' and v.get('kind') != 'clone' for v in voices), 'Base TTS voice unavailable'
        self.voice = 'Serena'  # Built-in voice on the existing base TTS model; no cloned model activation.
        result = self.request('POST', '/api/mlx/audio/speech', {'input': 'Dies ist der automatische MLX Nobby Audiotest.',
                              'voice': self.voice, 'language': 'de', 'response_format': 'mp3'}, timeout=self.timers['tts'])
        assert result.headers.get('content-type', '').startswith('audio/')
        assert len(result.content) > 500
        path = self.root / 'audio/speech.mp3'
        path.parent.mkdir()
        path.write_bytes(result.content)
        return inspect_media(path, 'audio')

    def open_chat(self, messages):
        histories = self.json('GET', '/api/mlx/chats')['chats']
        assert all(any(m.get('role') == 'user' for m in c.get('messages', [])) for c in histories), 'Browser history would clean legacy empty user chats; refusing to open it'
        self.own_chat(messages)
        if self.context:
            self.context.close()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.errors = []
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        # Seed only the disposable browser's normal saved session preference. No routes or media are mocked.
        self.context.add_init_script('localStorage.setItem("mlx-web-chats-v1", ' + json.dumps(json.dumps([self.chat])) + ');'
                                     'localStorage.setItem("mlx-nobby-sidebar-collapsed", "1");'
                                     'localStorage.setItem("mlx-nobby-language", "en");')
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('console', self.log_console)
        self.page.on('response', lambda response: self.network.append({'browser': True, 'url': response.url, 'method': response.request.method,
                                                                       'status': response.status}))
        self.page.goto(self.args.url + '/chat')
        from playwright.sync_api import expect
        expect(self.page.locator('.message.user')).to_contain_text(self.run_id)
        return self.page

    def log_console(self, message):
        self.console.append({'type': message.type, 'text': message.text})
        if message.type == 'error':
            self.errors.append(message.text)

    def finish_browser(self, name):
        assert not self.errors, 'Browser errors: ' + '\n'.join(self.errors)
        self.context.tracing.stop(path=str(self.root / ('browser-' + name + '.zip')))
        self.context.close()
        self.context = self.page = None

    def tts_playback(self):
        self.speech_ready()
        page = self.open_chat([{'role': 'assistant', 'content': 'Dies ist der automatische MLX Nobby Audiotest.'}])
        from playwright.sync_api import expect
        button = page.locator('.mlx-message-speech-button')
        # Normal voice selection UI, using a built-in voice without switching TTS models.
        voice_button = page.locator('#mlxVoiceButton')
        voice_button.click()
        page.locator('.mlx-voice-option').filter(has_text='Serena').click()
        page.keyboard.press('Escape')
        # Capture genuine Audio instances for observing events; keep the native constructor and play/pause implementations.
        page.evaluate('''() => {const AudioNative=window.Audio; window.__acceptanceAudio=[];
            window.Audio=function(...args) {const a=new AudioNative(...args); window.__acceptanceAudio.push(a);
                a.addEventListener('playing',()=>a.dataset.acceptancePlaying='yes'); return a;};
            window.Audio.prototype=AudioNative.prototype;}''')
        button.click()
        expect(button).to_have_attribute('aria-busy', 'true')
        expect(button).to_have_attribute('data-speech-state', 'playing', timeout=int(self.timers['tts'] * 1000))
        page.wait_for_function('window.__acceptanceAudio[0]?.currentTime > .1 && window.__acceptanceAudio[0]?.dataset.acceptancePlaying === "yes"')
        button.click()
        expect(button).to_have_attribute('data-speech-state', 'paused')
        paused = page.evaluate('window.__acceptanceAudio[0].currentTime')
        page.wait_for_timeout(200)
        assert abs(page.evaluate('window.__acceptanceAudio[0].currentTime') - paused) < .1
        button.click()
        expect(button).to_have_attribute('data-speech-state', 'playing')
        page.wait_for_function('(t) => window.__acceptanceAudio[0].currentTime > t+.1', arg=paused)
        # Let this short sample end naturally; no additional chat or model is created.
        expect(button).to_have_attribute('data-speech-state', 'idle', timeout=30000)
        page.wait_for_function('window.__acceptanceAudio[0].paused && !window.__acceptanceAudio[0].getAttribute("src")')
        self.finish_browser('speech')
        return {'playing_event': True, 'current_time_advanced': True, 'pause_resume': True, 'cleanup': True}

    def require_model(self, kind):
        self.readiness(kind)
        model = self.image_model if kind == 'image' else self.video_model
        if not model or not model.get('enabled') or not model.get('available'):
            raise Skip(f'Configured {kind} provider is not installed/available; no model selected')
        return model

    def start_job(self, kind, profile='standard'):
        self.require_model(kind)
        if not self.chat:
            self.own_chat([])
        prompt = 'A red ceramic mug on a plain wooden table, simple studio photo' if kind == 'image' else 'A red ball rolling slowly across a white table'
        payload = {'prompt': prompt, 'action': kind + '_generate', 'resolved_target': kind,
                   'chat_id': self.chat_id, 'chat_revision': self.chat['revision'], 'run_id': self.run_id,
                   'quality': 'fast' if kind == 'image' else 'preview'}
        if kind == 'image':
            payload['image_options'] = {'model': self.image_model['id'], 'width': 512, 'height': 512,
                                        'auto_size': False, 'seed': 42}
        else:
            payload['video_options'] = {'model': self.video_model['id'], 'profile': profile,
                                        'resolution': 'preview', 'duration': 2, 'fps': 8, 'seed': 42}
        path = '/api/mlx/chat/actions' if kind == 'image' else '/api/mlx/video/jobs'
        result = self.json('POST', path, payload, timeout=90, expected=(200, 202))
        job = result.get('data', {}).get('job')
        assert job and job.get('id') and job.get('status') == 'queued', f'{kind} was not queued: {result}'
        assert job.get('chat_id') == self.chat_id and job.get('run_id') == self.run_id
        self.jobs.append((kind, job['id']))
        return result

    def poll(self, kind, job_id, timeout, until=None):
        deadline = time.monotonic() + timeout
        snapshots, result = [], None
        while time.monotonic() < deadline:
            result = self.json('GET', f'/api/mlx/{kind}-jobs/{job_id}', timeout=min(20, max(1, deadline-time.monotonic())))
            job = result['data']['job']
            snapshots.append({k: job.get(k) for k in ('id', 'status', 'phase', 'progress', 'current_step', 'native_job_id')})
            (self.root / f'{kind}-{job_id}-polls.json').write_text(json.dumps(snapshots, indent=2))
            if until and until(job):
                break
            if result['status'] in TERMINAL:
                assert not until, f'{kind} {job_id} reached {result["status"]} before requested state'
                break
            time.sleep(.5)
        else:
            raise AssertionError(f'{kind} timeout; job={job_id}; last={snapshots[-1] if snapshots else None}')
        (self.root / f'{kind}-{job_id}-polls.json').write_text(json.dumps(snapshots, indent=2))
        return result, snapshots

    def generate(self, kind):
        initial = self.start_job(kind)
        result, snapshots = self.poll(kind, initial['data']['job']['id'], self.timers[kind])
        assert result['status'] == 'completed', f'{kind} failed: {result.get("error")}'
        assert len({(s['phase'], s['progress']) for s in snapshots}) > 1, 'No media progress observed'
        artifact = result['artifacts'][0]
        (self.root / f'{kind}-job-result.json').write_text(json.dumps(result, indent=2))
        media_id = artifact[kind + '_id']
        response = self.request('GET', f'/api/mlx/{kind}s/{media_id}', timeout=60)
        assert response.headers.get('content-type', '').startswith(kind + '/')
        directory = self.root / kind
        directory.mkdir(exist_ok=True)
        path = directory / ('result.png' if kind == 'image' else 'result.mp4')
        path.write_bytes(response.content)
        if kind == 'image':
            self.image_result = result
            detail = inspect_image(response.content)
        else:
            self.video_result = result
            assert len(response.content) > 1000
            inspect_preview(artifact)
            detail = inspect_media(path, 'video')
            if artifact.get('audio'):
                assert any(s['codec_type'] == 'audio' for s in detail['streams']), 'Contract promised video audio'
        return detail

    def image_preview(self):
        if not self.image_result:
            raise Skip('No image output from generation check')
        page = self.open_chat([{'role': 'assistant', 'content': '', 'tool_result': self.image_result,
                               'image_job': self.image_result['data']['job']}])
        from playwright.sync_api import expect
        image = page.locator('.image-artifact-preview')
        expect(image).to_be_visible()
        image.evaluate('(img) => img.decode()')
        assert image.evaluate('(img) => img.naturalWidth > 0 && img.naturalHeight > 0')
        image.click()
        expect(page.locator('.image-preview-dialog')).to_be_visible()
        page.locator('.image-preview-dialog button').click()
        expect(page.locator('.image-preview-dialog')).not_to_be_visible()
        self.finish_browser('image')

    def video_playback(self):
        if not self.video_result:
            raise Skip('No video output from preview check')
        page = self.open_chat([{'role': 'assistant', 'content': '', 'tool_result': self.video_result,
                               'video_job': self.video_result['data']['job']}])
        player = page.locator('.video-artifact-player')
        player.wait_for()
        player.evaluate('''video => {video.muted=true; video.addEventListener('playing',()=>video.dataset.acceptancePlaying='yes');}''')
        page.wait_for_function('''() => {const v=document.querySelector('video');return v && v.readyState>=1 && v.duration>0;}''')
        player.evaluate('(v) => v.play()')
        page.wait_for_function('''() => {const v=document.querySelector('video');return v.dataset.acceptancePlaying==='yes' && v.currentTime>.1;}''')
        player.evaluate('(v) => v.pause()')
        paused = player.evaluate('(v) => v.currentTime')
        page.wait_for_timeout(200)
        assert abs(player.evaluate('(v) => v.currentTime') - paused) < .1
        player.evaluate('(v) => v.play()')
        page.wait_for_function('(t) => document.querySelector("video").currentTime > t+.1', arg=paused)
        player.evaluate('(v) => v.pause()')
        self.finish_browser('video')
        return {'metadata': True, 'playing_event': True, 'current_time_advanced': True, 'pause_resume': True}

    def cancel_video(self):
        initial = self.start_job('video')
        job_id = initial['data']['job']['id']
        active, _ = self.poll('video', job_id, 90,
                              until=lambda job: bool(job.get('native_job_id')) and job['status'] == 'generating')
        native_id = active['data']['job']['native_job_id']
        native_before = self.native_json(self.args.video_url + '/jobs/' + native_id)
        assert native_before['status'] in {'loading', 'generating'}, 'Cancel requires an active native worker'
        assert self.native_json(self.args.video_url + '/health').get('active_generation') is True
        result = self.json('POST', f'/api/mlx/video-jobs/{job_id}/cancel', {}, timeout=40)
        cancelled, _ = self.poll('video', job_id, 60)
        assert cancelled['status'] == 'cancelled'
        native_id = cancelled['data']['job']['native_job_id']
        native = self.native_json(self.args.video_url + '/jobs/' + native_id)
        assert native['status'] == 'cancelled' and not native.get('result'), 'Native worker did not terminate cancellation'
        # Observe terminal stability across two normal UI poll intervals, then stop polling.
        time.sleep(2)
        stable = self.json('GET', f'/api/mlx/video-jobs/{job_id}')
        assert stable['status'] == 'cancelled' and not stable['artifacts']
        assert self.native_json(self.args.video_url + '/health').get('active_generation') is False
        return {'native_active_before_cancel': True, 'cancel_2xx': True,
                'native_cancelled': True, 'no_completed_result': True}

    def profiles(self):
        self.readiness('video')
        profiles = self.video_models.get('profiles', {})
        assert isinstance(profiles.get('uncensored_available'), bool)
        if profiles['uncensored_available']:
            return {'available': True, 'generation_attempted': False}
        self.require_model('video')
        before = {j['id'] for j in self.json('GET', '/api/system/job-queue')['jobs']}
        # Server preflight rejects this harmless prompt before creating any queue job.
        payload = {'prompt': 'A red ball', 'action': 'video_generate', 'chat_id': self.chat_id,
                   'chat_revision': self.chat['revision'], 'run_id': self.run_id,
                   'quality': 'preview', 'video_options': {'profile': 'uncensored', 'duration': 2, 'resolution': 'preview'}}
        response = self.request('POST', '/api/mlx/video/jobs', payload, expected=(400, 422, 503))
        assert 'uncensored' in response.text.lower() and ('unavailable' in response.text.lower() or 'konfiguriert' in response.text.lower())
        after = {j['id'] for j in self.json('GET', '/api/system/job-queue')['jobs']}
        assert before == after, 'Unavailable profile created a job'
        return {'available': False, 'controlled_rejection': True, 'no_job': True}

    def shorts(self):
        self.json('GET', '/api/mlx/shorts/capabilities')
        project = {'schema_version': 2, 'title': self.run_id, 'briefing': self.run_id, 'duration': 5,
                   'quality': 'fast', 'voice_enabled': False, 'music_enabled': False, 'subtitles_enabled': False,
                   'consistency_mode': False, 'scenes': [{'id': 'scene-1', 'duration': 5,
                   'description': 'A red ball on a white table', 'video_prompt': 'A red ball rolling slowly across a white table'}]}
        draft = self.json('POST', '/api/mlx/shorts/drafts', {'project': project, 'chat_id': self.chat_id}, expected=(201,))['draft']
        self.drafts.append(draft['id'])
        read = self.json('GET', '/api/mlx/shorts/drafts/' + draft['id'])['draft']
        assert read['project']['title'] == self.run_id and read['chat_id'] == self.chat_id
        preflight = self.json('GET', '/api/mlx/shorts/drafts/' + draft['id'] + '/preflight', timeout=60)
        assert preflight['available'], preflight
        return {'created': True, 'read': True, 'preflight': True}

    def full_short(self):
        if not self.args.full:
            raise Skip('Opt in with --full; minimum Shorts contract is one 5-second 540p scene')
        self.require_model('video')
        assert self.drafts, 'No validated Shorts draft'
        job = self.json('POST', '/api/mlx/shorts/drafts/' + self.drafts[0] + '/render', {}, expected=(202,))['job']
        self.jobs.append(('shorts', job['id']))
        result, _ = self.poll('shorts', job['id'], self.timers['video'])
        assert result['status'] == 'completed', result.get('error')
        response = self.request('GET', '/api/mlx/shorts/' + job['id'], timeout=60)
        path = self.root / 'short.mp4'
        path.write_bytes(response.content)
        return inspect_media(path, 'video')

    def cleanup(self):
        if self.context:
            try:
                self.context.tracing.stop(path=str(self.root / 'browser-failure.zip'))
            finally:
                self.context.close()
                self.context = self.page = None
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        for kind, job_id in self.jobs:
            result = self.json('GET', f'/api/mlx/{kind}-jobs/{job_id}')
            job = result['data']['job']
            assert job.get('chat_id') == self.chat_id, 'Refusing cleanup of a foreign job'
            if result['status'] not in TERMINAL:
                self.json('POST', f'/api/mlx/{kind}-jobs/{job_id}/cancel', {}, timeout=40)
                terminal, _ = self.poll(kind, job_id, 60)
                assert terminal['status'] in TERMINAL, 'Own job did not stop'
        for draft_id in self.drafts:
            draft = self.json('GET', '/api/mlx/shorts/drafts/' + draft_id)['draft']
            assert draft['chat_id'] == self.chat_id and draft['project']['title'] == self.run_id
            self.request('DELETE', '/api/mlx/shorts/drafts/' + draft_id)
        if self.chat:
            own = self.json('GET', '/api/mlx/chats/' + self.chat_id)['chat']
            assert own['id'] == self.chat_id and own['title'] == self.run_id
            # Retain image ownership references when later browser views replace the active test turn.
            if self.image_result:
                self.own_chat([{'role': 'assistant', 'content': '', 'tool_result': self.image_result}])
            self.request('DELETE', '/api/mlx/chats/' + self.chat_id)
        if self.before.get('chat', {}).get('online'):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                after = self.json('GET', '/api/mlx/status')
                assert after.get('model') == self.before['chat'].get('model'), 'Chat model changed; acceptance never selects another model'
                if after.get('online'):
                    break
                time.sleep(1)
            else:
                raise AssertionError('Original chat runtime was not restored by the production coordinator')
        if self.before.get('services'):
            after_services = self.json('GET', '/api/mlx/services/health')
            after_chat = self.json('GET', '/api/mlx/status')
            (self.root / 'state-after.json').write_text(json.dumps(
                {'services': after_services, 'chat': after_chat}, indent=2))
            online = {s['name'] for s in after_services.get('services', []) if s.get('online')}
            original = {s['name'] for s in self.before['services'].get('services', []) if s.get('online')}
            assert original <= online, 'Previously online services went offline: ' + ', '.join(sorted(original - online))
        return {'own_chats_drafts_removed': True, 'jobs': self.jobs,
                'media_retention': 'Native terminal job/video records use existing service retention; no global cleanup'}

    def run(self):
        try:
            self.check('Preflight', self.preflight)
            if self.results[-1]['status'] == 'PASS':
                for name, fn in [('Chat', self.chat_test), ('Gateway', self.gateway),
                             ('Read Aloud Generation', self.tts), ('Read Aloud Playback', self.tts_playback),
                             ('Image Generate', lambda: self.generate('image')), ('Image Browser Preview', self.image_preview),
                             ('Video Preview', lambda: self.generate('video')), ('Video Playback', self.video_playback),
                             ('Video Cancel', self.cancel_video), ('Uncensored Capability', self.profiles),
                             ('Shorts Draft', self.shorts), ('Shorts Full', self.full_short)]:
                    self.check(name, fn)
        except KeyboardInterrupt:
            self.results.append({'name': 'Interrupted', 'status': 'FAIL', 'seconds': 0,
                                 'detail': {'error': 'Interrupted; cleaning up only owned resources'}})
        finally:
            self.check('Cleanup / Runtime State', self.cleanup)
            self.client.close()
        elapsed = round(time.monotonic() - self.started, 2)
        passed = all(row['status'] != 'FAIL' for row in self.results)
        summary = {'run_id': self.run_id, 'duration_seconds': elapsed, 'result': 'PASS' if passed else 'FAIL',
                   'checks': self.results}
        (self.root / 'summary.json').write_text(json.dumps(summary, indent=2))
        (self.root / 'network.json').write_text(json.dumps(self.network, indent=2))
        (self.root / 'console.json').write_text(json.dumps(self.console, indent=2))
        lines = ['MLX NOBBY REAL ACCEPTANCE', *[f'{r["name"]:26} {r["status"]}' for r in self.results],
                 f'Duration: {elapsed}s', 'RESULT: ' + summary['result'], 'Artifacts: ' + str(self.root)]
        (self.root / 'summary.txt').write_text('\n'.join(lines) + '\n')
        print('\n'.join(lines), flush=True)
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', type=loopback_url, default='http://127.0.0.1:8090')
    parser.add_argument('--speech-url', type=loopback_url, default='http://127.0.0.1:8050')
    parser.add_argument('--video-url', type=loopback_url, default='http://127.0.0.1:8060')
    parser.add_argument('--full', action='store_true', help='Also render one 5-second 540p Short')
    for name, default in [('chat', 90), ('tts', 90), ('image', 300), ('video', 360)]:
        parser.add_argument(f'--{name}-timeout', type=float, default=default)
    args = parser.parse_args(argv)
    if any(getattr(args, name + '_timeout') <= 0 for name in ('chat', 'tts', 'image', 'video')):
        parser.error('Timeouts must be positive')
    return Acceptance(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
