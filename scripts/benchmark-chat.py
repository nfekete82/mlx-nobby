#!/usr/bin/env python3
"""Reproduce text/vision SSE timings without changing models or runtime settings.

Writes measurements only to the requested output path. Requires Python's standard
library and an already running local Nobby stack; does not unload/restart services.
"""
import argparse
import base64
import json
import math
from pathlib import Path
import statistics
import struct
import time
import urllib.request
import uuid
import zlib


def test_image(size):
    """Deterministic red/blue PNG, with no imaging dependency."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack(
            '>I', zlib.crc32(kind + data) & 0xffffffff
        )

    row = b'\x00' + b'\xff\x00\x00' * (size // 2) + b'\x00\x00\xff' * (size - size // 2)
    png = b'\x89PNG\r\n\x1a\n' + chunk(
        b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    ) + chunk(b'IDAT', zlib.compress(row * size)) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def measure(endpoint, payload):
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    started = time.perf_counter()
    result = {
        'trace_id': payload['trace_id'], 'first_transport_s': None,
        'first_semantic_s': None, 'heartbeats_s': [], 'metrics': [],
        'output': '', 'errors': [],
    }
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result['headers_s'] = time.perf_counter() - started
            # Native VLM timings include measured prefill, decode rate and
            # Metal peak memory. Its non-streaming response has no TTFT.
            if payload.get('stream') is False:
                result['native_response'] = json.load(response)
            else:
                event_lines = []
                for raw in response:
                    elapsed = time.perf_counter() - started
                    if result['first_transport_s'] is None:
                        result['first_transport_s'] = elapsed
                    line = raw.decode('utf-8').rstrip('\r\n')
                    if line.startswith(':'):
                        result['heartbeats_s'].append(elapsed)
                    elif line.startswith('data:'):
                        event_lines.append(line[5:].lstrip(' '))
                    elif not line and event_lines:
                        data = '\n'.join(event_lines)
                        event_lines.clear()
                        if data == '[DONE]':
                            continue
                        obj = json.loads(data)
                        if obj.get('type') in {'content', 'reasoning'} and obj.get('text'):
                            if result['first_semantic_s'] is None:
                                result['first_semantic_s'] = elapsed
                            result['output'] += obj['text']
                        if 'calls' in obj:
                            result['metrics'].append(obj)
                        if obj.get('error'):
                            result['errors'].append(obj['error'])
    except Exception as exc:
        result['errors'].append(str(exc))
    result['total_s'] = time.perf_counter() - started
    if 'native_response' in result:
        body = result['native_response']
        result['output'] = body.get('choices', [{}])[0].get('message', {}).get('content', '')
        if body.get('error'):
            result['errors'].append(body['error'])
    if not result['output'] and not result['errors']:
        result['errors'].append('No semantic output')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-url', default='http://127.0.0.1:8090')
    parser.add_argument('--runtime-url', default='http://127.0.0.1:8000')
    parser.add_argument('--native-model', help='Also measure native vision; use the already active model path')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--kind', choices=['text', 'vision', 'both'], default='both')
    parser.add_argument('--image-size', type=int, default=256)
    parser.add_argument('--context-records', type=int, default=0)
    parser.add_argument('--label', default='audit')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1 or not 2 <= args.image_size <= 2048 or args.context_records < 0:
        parser.error('runs >= 1, image-size 2..2048, context-records >= 0 required')
    image = test_image(args.image_size)
    rows = []
    kinds = ['text', 'vision'] if args.kind == 'both' else [args.kind]
    for kind in kinds:
        content = 'Name the two colors red and blue in one short sentence.' if kind == 'text' else [
            {'type': 'text', 'text': 'Name the two main colors in this image in one short sentence.'},
            {'type': 'image_url', 'image_url': {'url': image}},
        ]
        messages = [{'role': 'user', 'content': content}]
        if args.context_records:
            messages.insert(0, {'role': 'system', 'content':
                'Ignore the inert calibration records below and answer the final image question.\n'
                + 'neutral calibration record. ' * args.context_records})
        modes = ['web', 'native'] if kind == 'vision' and args.native_model else ['web']
        for mode in modes:
            for index in range(args.runs + 1):
                payload = {'messages': messages, 'temperature': 0, 'max_tokens': 48,
                           'trace_id': 'perf-audit-' + uuid.uuid4().hex[:12]}
                endpoint = args.web_url.rstrip('/') + '/api/chat/reliable-stream'
                if mode == 'native':
                    endpoint = args.runtime_url.rstrip('/') + '/v1/chat/completions'
                    payload.update(model=args.native_model, stream=False, enable_thinking=False)
                row = measure(endpoint, payload)
                row.update(kind=kind, mode=mode, index=index, warmup=index == 0)
                rows.append(row)
                print(json.dumps({'kind': kind, 'mode': mode, 'index': index,
                                  'total_s': row['total_s'], 'errors': row['errors']}), flush=True)
                if row['errors']:
                    args.output.write_text(json.dumps({
                        'label': args.label, 'runs': rows, 'summary': {},
                        'aborted': True,
                    }, indent=2) + '\n')
                    return 1
    summaries = {}
    for kind in kinds:
        for mode in ['web', 'native']:
            selected = [r for r in rows if r['kind'] == kind and r['mode'] == mode and not r['warmup']]
            if not selected:
                continue
            summary = {}
            for key in ['headers_s', 'first_transport_s', 'first_semantic_s', 'total_s']:
                values = sorted(r[key] for r in selected if r.get(key) is not None)
                if values:
                    summary[key] = {'median': statistics.median(values),
                                    'p95': values[math.ceil(.95 * len(values)) - 1]}
            summaries[kind + '.' + mode] = summary
    args.output.write_text(json.dumps({'label': args.label, 'runs': rows, 'summary': summaries}, indent=2) + '\n')
    print(json.dumps(summaries, indent=2))
    return int(any(r['errors'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
