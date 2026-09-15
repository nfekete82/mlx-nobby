import asyncio
"""CPU-only HTTP regressions; native networking, FFmpeg and inference are mocked."""
import importlib.util
import io
import json
import sys
import types
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import service_proxy
from backend import app as web
from backend import observability
from local_security import LocalRequestGuard


def upstream_response(body=b'{"text":"hello"}', status=200):
    response = io.BytesIO(body)
    response.status = status
    response.headers = Message()
    response.headers['Content-Type'] = 'application/json'
    return response


class ServiceBridgeTests(unittest.TestCase):
    def setUp(self):
        observability.reset_metrics()
        self.bridge = FastAPI()
        self.bridge.add_middleware(LocalRequestGuard)
        self.lock = MagicMock()
        service_proxy.install_routes(self.bridge, lambda: 8123, self.lock)
        self.agent_client = TestClient(self.bridge, base_url='http://localhost')
        self.web_client = TestClient(web.app, base_url='http://localhost')
        self.addCleanup(self.agent_client.close)
        self.addCleanup(self.web_client.close)

    def test_audio_route_through_agent_and_native_handler(self):
        # Load the real speech HTTP handler without importing any MLX package.
        stt = types.ModuleType('mlx_audio.stt')
        stt.load = Mock(side_effect=AssertionError('Real model loading is forbidden'))
        spec = importlib.util.spec_from_file_location('speech_test_service', Path(__file__).parents[1] / 'speech/app.py')
        speech = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'mlx_audio': types.ModuleType('mlx_audio'), 'mlx_audio.stt': stt}):
            spec.loader.exec_module(speech)
        native_client = TestClient(speech.app, base_url='http://localhost')
        self.addCleanup(native_client.close)
        requests = []

        def open_local(request, timeout):
            requests.append(request)
            if request.full_url == web.SPEECH_URL + '/v1/audio/transcriptions':
                client, path = self.agent_client, '/api/bridge/speech/v1/audio/transcriptions'
            elif request.full_url == 'http://127.0.0.1:8050/v1/audio/transcriptions':
                client, path = native_client, '/v1/audio/transcriptions'
            else:
                raise AssertionError('Unexpected native request: ' + request.full_url)
            result = client.post(path, content=request.data, headers={'Content-Type': request.get_header('Content-type')})
            response = upstream_response(result.content, result.status_code)
            if result.status_code >= 400:
                raise urllib.error.HTTPError(request.full_url, result.status_code, 'native error', response.headers, response)
            return response

        model = Mock()
        model.generate.return_value = '  hello  '
        with patch.dict('os.environ', {'SPEECH_SERVICE_URL': 'http://127.0.0.1:8050'}), \
                patch.object(service_proxy.urllib.request, 'urlopen', side_effect=open_local), \
                patch.object(speech.subprocess, 'run', return_value=Mock(returncode=0, stderr='')) as ffmpeg, \
                patch.object(speech, 'get_model', return_value=model):
            response = self.web_client.post('/api/mlx/audio/transcriptions', files={'file': ('original.WEBM', b'audio bytes', 'audio/webm')})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['text'], 'hello')
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0].data, requests[1].data)
            self.assertIn(b'filename="recording.webm"', requests[0].data)
            self.assertIn(b'audio bytes', requests[0].data)
            self.assertIn('boundary=----MLXSpeech', requests[0].get_header('Content-type'))
            ffmpeg.assert_called_once()
            model.generate.assert_called_once()
            ffmpeg.return_value = Mock(returncode=1, stderr='test conversion failure')
            failed = self.web_client.post('/api/mlx/audio/transcriptions', files={'file': ('audio.wav', b'audio bytes')})
            self.assertEqual(failed.status_code, 500)
            self.assertIn('test conversion failure', failed.json()['detail'])

    def test_audio_rejects_invalid_empty_and_oversized_uploads(self):
        with patch.object(web, 'MAX_UPLOAD_SIZE_BYTES', 4), patch.object(web.urllib.request, 'urlopen') as network:
            for filename, data, status in [('audio.exe', b'abc', 415), ('audio.wav', b'', 400), ('audio.wav', b'abcde', 413)]:
                with self.subTest(filename=filename, status=status):
                    response = self.web_client.post('/api/mlx/audio/transcriptions', files={'file': (filename, data)})
                    self.assertEqual(response.status_code, status, response.text)
            network.assert_not_called()

    def test_mlx_bridge_uses_runtime_port_and_lock(self):
        payload = {'model': 'owner/model', 'messages': [{'role': 'user', 'content': 'hello'}], 'stream': False}
        with patch.object(service_proxy.urllib.request, 'urlopen', side_effect=lambda *a, **k: upstream_response()) as network:
            self.assertEqual(self.agent_client.get('/api/bridge/mlx/v1/models').status_code, 200)
            self.assertEqual(network.call_args.args[0].full_url, 'http://127.0.0.1:8123/v1/models')
            response = self.agent_client.post('/api/bridge/mlx/v1/chat/completions', json=payload)
            self.assertEqual(response.status_code, 200)
            request = network.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8123/v1/chat/completions')
            self.assertEqual(json.loads(request.data), payload)
            self.lock.__enter__.assert_called_once()
            self.lock.__exit__.assert_called_once()


    def test_text_chat_stream_close_closes_upstream_response(self):
        class FakeUpstreamResponse:
            def __init__(self):
                self.closed = False
                self.entered = False
                self.exited = False
                self.lines_consumed = 0

            def __enter__(self):
                self.entered = True
                return self

            def __exit__(self, exc_type, exc, tb):
                self.exited = True
                self.close()
                return False

            def __iter__(self):
                return self

            def __next__(self):
                self.lines_consumed += 1

                if self.lines_consumed == 1:
                    return (
                        b'data: {"type":"content",'
                        b'"text":"hello"}\n\n'
                    )

                return (
                    b'data: {"type":"content",'
                    b'"text":"should-not-be-consumed"}\n\n'
                )

            def close(self):
                self.closed = True

        upstream = FakeUpstreamResponse()

        def open_local(request, timeout):
            self.assertEqual(
                request.full_url,
                web.AGENT_URL +
                "/api/runtime/chat/stream",
            )
            self.assertEqual(timeout, 900)
            return upstream

        with patch.object(
            web,
            "agent_json_request",
            return_value={},
        ), patch.object(
            web.urllib.request,
            "urlopen",
            side_effect=open_local,
        ):
            response = web.mlx_chat_stream(
                web.ChatRequest(
                    messages=[
                        {
                            "role": "user",
                            "content": "hello",
                        }
                    ],
                    trace_id="trace-cancel-backend",
                )
            )

            generator = response.body_iterator

            self.assertFalse(upstream.closed)

            first = asyncio.run(anext(generator))

            self.assertIn(
                b'"text":"hello"',
                first,
            )

            self.assertTrue(upstream.entered)
            self.assertFalse(upstream.closed)
            self.assertEqual(
                upstream.lines_consumed,
                1,
            )

            asyncio.run(generator.aclose())

        self.assertTrue(
            upstream.exited,
            "closing backend stream must exit upstream context",
        )
        self.assertTrue(
            upstream.closed,
            "closing backend stream must close upstream response",
        )
        self.assertEqual(
            upstream.lines_consumed,
            1,
            "backend must stop consuming upstream after close",
        )

    def test_vision_chat_preserves_all_images_in_one_native_request(self):
        image_urls = [
            f'data:image/png;base64,image-{index}'
            for index in range(1, 5)
        ]
        messages = [{
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': 'Compare the images.\n\nAdditional user files:\nnotes.txt',
                },
                *[
                    {
                        'type': 'image_url',
                        'image_url': {'url': url},
                    }
                    for url in image_urls
                ],
            ],
        }]
        forwarded_urls = []
        native_requests = []

        def open_local(request, timeout):
            forwarded_urls.append(request.full_url)

            if request.full_url == web.MLX_URL + '/v1/chat/completions':
                result = self.agent_client.post(
                    '/api/bridge/mlx/v1/chat/completions',
                    content=request.data,
                    headers={
                        'Content-Type': request.get_header('Content-type'),
                    },
                )
                return upstream_response(result.content, result.status_code)

            if request.full_url == 'http://127.0.0.1:8123/v1/chat/completions':
                native_requests.append(request)
                return upstream_response(
                    b'{"choices":[{"message":{"content":"compared"},'
                    b'"finish_reason":"stop"}],"usage":{"prompt_tokens":12,'
                    b'"completion_tokens":3,"total_tokens":15}}'
                )

            raise AssertionError('Unexpected request: ' + request.full_url)

        with patch.object(
            web,
            'agent_json_request',
            return_value={},
        ), patch.object(
            web,
            'get_json',
            return_value={'online': True, 'model': 'vision-model'},
        ), patch.object(
            service_proxy.urllib.request,
            'urlopen',
            side_effect=open_local,
        ):
            response = self.web_client.post(
                '/api/chat/stream',
                json={
                    'messages': messages,
                    'trace_id': 'trace-vision-001',
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(native_requests), 1)
        self.assertEqual(
            forwarded_urls,
            [
                web.MLX_URL + '/v1/chat/completions',
                'http://127.0.0.1:8123/v1/chat/completions',
            ],
        )

        payload = json.loads(native_requests[0].data)
        self.assertNotIn('_mlx_observability', payload)
        content = payload['messages'][0]['content']

        self.assertEqual(content[0]['type'], 'text')
        self.assertIn('notes.txt', content[0]['text'])
        self.assertEqual(
            [
                part['image_url']['url']
                for part in content
                if part.get('type') == 'image_url'
            ],
            image_urls,
        )
        metric_event = next(
            event for event in response.text.split('\n\n')
            if event.startswith('event: metrics')
        )
        snapshot = json.loads(
            next(
                line[5:].strip()
                for line in metric_event.splitlines()
                if line.startswith('data:')
            )
        )
        self.assertEqual(snapshot['trace_id'], 'trace-vision-001')
        self.assertEqual(snapshot['model_calls_in_turn'], 1)
        self.assertEqual(snapshot['calls'][0]['purpose'], 'chat.vision')
        self.assertEqual(
            snapshot['calls'][0]['usage']['count_method'],
            'upstream',
        )

    def test_compaction_uses_turn_trace_without_sending_metrics_to_model(self):
        native_requests = []

        def open_local(request, timeout):
            if request.full_url == web.MLX_URL + '/v1/chat/completions':
                result = self.agent_client.post(
                    '/api/bridge/mlx/v1/chat/completions',
                    content=request.data,
                    headers={
                        'Content-Type': request.get_header('Content-type'),
                    },
                )
                return upstream_response(result.content, result.status_code)

            if request.full_url == 'http://127.0.0.1:8123/v1/chat/completions':
                native_requests.append(request)
                return upstream_response(
                    b'{"choices":[{"message":{"content":"summary"},'
                    b'"finish_reason":"stop"}]}'
                )

            raise AssertionError('Unexpected request: ' + request.full_url)

        messages = [
            {'role': 'user', 'content': f'message {index}'}
            for index in range(13)
        ]
        messages[0].update({
            'trace_id': 'must-not-reach-model',
            '_context_sources': {'history': {'characters': 9, 'items': 1}},
            'model_metrics': {'private': 'must-not-reach-model'},
        })

        with patch.object(
            web,
            'get_json',
            return_value={'online': True, 'model': 'owner/chat-model'},
        ), patch.object(
            service_proxy.urllib.request,
            'urlopen',
            side_effect=open_local,
        ):
            response = self.web_client.post(
                '/api/chat/compact',
                json={
                    'messages': messages,
                    'trace_id': 'trace-compact-001',
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['compacted'])
        self.assertEqual(len(native_requests), 1)
        native_payload = json.loads(native_requests[0].data)
        prompt = native_payload['messages'][0]['content']
        self.assertNotIn('must-not-reach-model', prompt)
        self.assertNotIn('_context_sources', prompt)
        self.assertNotIn('model_metrics', prompt)
        snapshot = observability.trace_snapshot('trace-compact-001')
        self.assertEqual(snapshot['model_calls_in_turn'], 1)
        self.assertEqual(snapshot['calls'][0]['purpose'], 'chat.compact')

    def test_bridge_rejects_streaming_arbitrary_paths_and_nonmultipart_audio(self):
        with patch.object(service_proxy.urllib.request, 'urlopen') as network:
            self.assertEqual(self.agent_client.post('/api/bridge/mlx/v1/chat/completions', json={'stream': True}).status_code, 422)
            self.assertEqual(self.agent_client.get('/api/bridge/mlx/arbitrary').status_code, 404)
            self.assertEqual(self.agent_client.post('/api/bridge/speech/v1/audio/transcriptions', json={}).status_code, 415)
            network.assert_not_called()

    def test_bridge_preserves_upstream_errors_and_reports_unavailable_service(self):
        body = b'{"detail":"busy"}'
        reply = upstream_response(body, 429)
        upstream_error = urllib.error.HTTPError('http://localhost', 429, 'busy', reply.headers, reply)
        for error, status in [(upstream_error, 429), (urllib.error.URLError('offline'), 503)]:
            with self.subTest(status=status), patch.object(service_proxy.urllib.request, 'urlopen', side_effect=error):
                response = self.agent_client.get('/api/bridge/mlx/v1/models')
                self.assertEqual(response.status_code, status)
                if status == 429:
                    self.assertEqual(response.content, body)


if __name__ == '__main__':
    unittest.main()
