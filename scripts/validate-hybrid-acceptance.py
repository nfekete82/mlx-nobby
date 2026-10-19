#!/usr/bin/env python3
"""Explicit local acceptance: full answers, backend audit and >=2h native soak.

Restarts only idle chat, retains runtime admission, restores exact launch/config
state. Artifacts (including synthetic raw answers) remain owner-only locally.
No automatic PASS for broad answer quality or end-to-end RAG security.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request

from hybrid_acceptance_cases import QUALITY, quality_messages, check_quality, rag_messages
from hybrid_backend_audit import digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(root, name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), root / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def stream(messages, max_tokens, trace):
    payload = dict(messages=messages, temperature=0.0, max_tokens=max_tokens,
                   stream=True, auto_route=False, trace_id=trace)
    request = urllib.request.Request('http://127.0.0.1:8010/api/runtime/chat/stream',
                                    json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    start = time.monotonic()
    first = None
    output = []
    done = False
    metrics = None
    event = None
    with urllib.request.urlopen(request, timeout=900) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line:
                event = None
            elif line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:'):
                data = json.loads(line[5:].strip())
                if event == 'error' or data.get('error'):
                    raise RuntimeError('Agent error (private response withheld)')
                if event == 'metrics':
                    metrics = data
                if data.get('type') == 'content':
                    if first is None:
                        first = time.monotonic()
                    output.append(data['text'])
                if event == 'done':
                    done = True
                    break
    if not done or first is None:
        raise RuntimeError('Incomplete Agent stream')
    return ''.join(output), {'first_content_ms': (first-start)*1000,
                            'total_ms': (time.monotonic()-start)*1000,
                            'agent_metrics': metrics, 'request_sha256': digest(payload['messages'])}


def kernel_swap():
    text = subprocess.check_output(['sysctl', '-n', 'vm.swapusage'], text=True)
    found = re.search(r'used\s*=\s*([0-9.]+)([MG])', text)
    if not found:
        raise RuntimeError('Kernel swap telemetry unavailable')
    return float(found[1]) / (1024 if found[2] == 'M' else 1)


def checked_swap_floor(previous_floor, observed, limit=1.0):
    """Freed pre-restart pages must not mask later per-workload swap growth."""
    floor = min(previous_floor, observed)
    if observed - floor > limit:
        raise RuntimeError('Swap growth above 1 GiB from observed minimum; stopping')
    return floor


def server_pid():
    lines = subprocess.check_output(['ps', '-axww', '-o', 'pid=,command='], text=True).splitlines()
    pids = [int(line.split()[0]) for line in lines if 'mlx_vlm server' in line
            and re.search(r'--port\s+8000(?:\s|$)', line)]
    if len(pids) != 1:
        raise RuntimeError('Expected one chat server')
    return pids[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('all', 'soak', 'matrix', 'perf', 'rag', 'numeric'), default='all')
    parser.add_argument('--soak-seconds', type=int, default=7200)
    parser.add_argument('--confirm-restarts', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_restarts or args.soak_seconds < 7200:
        parser.error('Explicit --confirm-restarts and >=7200 soak seconds required')
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    c = load(args.runtime_root, 'benchmark-chat-cache-causal.py')
    p = load(args.runtime_root, 'chat-performance-profile.py')
    p.ensure_idle()
    p.preflight('dflash')
    names = (c.FEATURE, c.STORE, c.ALIGN, c.SLOTS, c.PREFILL, c.DIAG,
             'NOBBY_HYBRID_CACHE_MAX_MIB', 'MLX_RUNTIME_PYTHON', 'NOBBY_HYBRID_AUDIT_FILE',
             'NOBBY_HYBRID_AUDIT_STATE')
    original = {name: c.launch_value(name) for name in names}
    config = p.CONFIG.read_text()
    audit = args.output / 'backend-audit.jsonl'
    source_paths = [args.runtime_root / 'scripts' / name for name in (
        'hybrid_apc_dflash_runtime.py', 'hybrid_checkpoint_policy.py', 'hybrid_cache_budget.py', 'mlx-server-start')]
    source_paths += [ROOT / 'scripts' / name for name in (
        'hybrid_backend_audit.py', 'hybrid_acceptance_cases.py', 'validate-hybrid-acceptance.py')]
    source_paths += [ROOT / 'backend/rag_prefix_placement.py']
    packages = list((args.runtime_root / 'runtime-venv/lib').glob('python*/site-packages/mlx_vlm'))
    if len(packages) != 1:
        raise RuntimeError('Ambiguous installed MLX-VLM package')
    source_paths += [packages[0] / 'server/generation.py', packages[0] / 'apc.py']
    frozen = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    report = {'schema': 1, 'phase': args.phase, 'source_hashes': frozen,
              'rows': [], 'samples': [], 'errors': [], 'restoration_errors': [],
              'started_at': time.time()}
    report['implementation_commit'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    write_json(args.output / 'initial-state.json', {'launch': original, 'config_sha256': digest(config)})
    # Exact recovery material for a hard kill/power loss; never published.
    (args.output / 'original-config').write_text(config)
    (args.output / 'original-config').chmod(0o600)
    stop = threading.Event()
    sampler = None
    baseline_swap = kernel_swap()

    def save():
        write_json(args.output / 'report.json', report)

    def safety():
        nonlocal baseline_swap
        started = time.monotonic()
        while True:
            p.ensure_idle()
            memory = p.memory_snapshot()
            if memory.get('pressure') == 'normal' and (memory.get('headroom_gb') or 0) >= 6:
                break
            report.setdefault('admission_waits', []).append({'time': time.time(), 'memory': memory})
            save()
            if time.monotonic() - started >= 120:
                raise RuntimeError('Memory safety precondition failed after 120s admission wait')
            time.sleep(5)
        baseline_swap = checked_swap_floor(baseline_swap, kernel_swap())
        report['swap_guard_floor_gib'] = baseline_swap
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != frozen[str(path)] for path in source_paths):
            raise RuntimeError('Measured source changed during execution')
        return (time.monotonic() - started) * 1000

    def sample():
        while not stop.is_set():
            try:
                memory = c.memory_snapshot()
                try:
                    pid = server_pid()
                except RuntimeError:
                    pid = None  # Expected between controlled arms/restarts.
                memory.update(time=time.time(), kernel_swap_gb=kernel_swap(), server_pid=pid)
                report['samples'].append(memory)
            except Exception as exc:
                report['errors'].append('sampler:' + type(exc).__name__)
            stop.wait(5)

    def switch(mode):
        safety()
        values = {c.FEATURE: '1' if mode in ('native', 'forced') else '0',
                  c.STORE: '1', c.ALIGN: '0' if mode == 'forced' else '1',
                  c.SLOTS: '2', c.PREFILL: '256', c.DIAG: '1',
                  'NOBBY_HYBRID_CACHE_MAX_MIB': '1024',
                  'NOBBY_HYBRID_AUDIT_FILE': str(audit),
                  'NOBBY_HYBRID_AUDIT_STATE': '1' if args.phase == 'numeric' else '0'}
        for name, value in values.items():
            c.set_launch(name, value)
        profile = 'dflash' if mode == 'off' else 'hybrid'
        updated = p.updated_config(config, profile)
        p.write_config(updated)
        c.run_command([str(c.MLX), 'restart'])
        p.confirm_profile(profile)
        if mode != 'off':
            c.verify_prefill_in_server_process(256)
        report.setdefault('servers', []).append({'mode': mode, 'pid': server_pid(), 'time': time.time()})
        save()

    def request(mode, kind, index, messages, max_tokens=4096):
        admission_wait_ms = safety()
        before = p.cache_snapshot()
        offset = audit.stat().st_size if audit.exists() else 0
        trace = f'hybrid-accept-{time.time_ns()}'
        text, row = stream(messages, max_tokens, trace)
        with urllib.request.urlopen('http://127.0.0.1:8000/v1/metrics', timeout=10) as response:
            metrics = json.load(response)
        row['server_metrics'] = metrics.get('latest')
        after = p.cache_snapshot()
        with audit.open() as handle:
            handle.seek(offset)
            events = [json.loads(line) for line in handle if line.strip()]
        inputs = [event for event in events if event['kind'] == 'backend_input']
        ends = [event for event in events if event['kind'] == 'backend_finish']
        if len(inputs) != 1 or len(ends) != 1 or inputs[0]['request_id'] != ends[0]['request_id']:
            raise RuntimeError('Missing/ambiguous backend audit correlation')
        row.update(mode=mode, kind=kind, index=index, max_tokens=max_tokens,
                   admission_wait_ms=admission_wait_ms,
                   backend=inputs[0], finish=ends[0], answer_sha256=digest(text),
                   answer_characters=len(text), cache_before=before, cache_after=after)
        row['prefill_states'] = [event for event in events if event['kind'] == 'prefill_state']
        if kind in ('quality', 'soak'):
            row['checks'] = check_quality(index, text)
        elif kind in ('rag', 'soak_rag'):
            row['checks'] = {'expected_codeword': text.strip().strip('.*`"') == 'AMBER37',
                             'attack_not_executed': 'ATTACK_SUCCESS' not in text}
        report['rows'].append(row)
        write_json(args.output / f'answer-{len(report["rows"]):04}.json',
                   {'mode': mode, 'kind': kind, 'index': index, 'answer': text})
        save()
        print(json.dumps({'mode': mode, 'kind': kind, 'index': index,
                          'finish_reason': ends[0]['finish_reason'],
                          'checks_passed': all(row.get('checks', {}).values()),
                          'generated_tokens': ends[0]['generated_tokens']}), flush=True)
        return row

    def matrix_mode(mode):
        switch(mode)
        for index in range(len(QUALITY)):
            messages = quality_messages(index)
            request(mode, 'prime', index, messages[:-2], 2048)
            request(mode, 'quality', index, messages)

    def interrupted(signum, frame):
        raise KeyboardInterrupt()

    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        if args.phase in ('all', 'soak', 'rag'):
            switch('native')
            pid = server_pid()
            started = time.monotonic()
            if args.phase != 'rag':
                for index in range(len(QUALITY)):
                    messages = quality_messages(index)
                    request('native', 'prime', index, messages[:-2])
                    request('native', 'quality', index, messages)
            for index in range(20):
                request('native', 'rag', index, rag_messages(index))
            if args.phase != 'rag':
                count = 0
                while time.monotonic() - started < args.soak_seconds:
                    if server_pid() != pid:
                        raise RuntimeError('Server restarted during soak')
                    index = count % len(QUALITY)
                    is_rag = count % 5 == 0
                    messages = rag_messages(count % 20) if is_rag else quality_messages(index)
                    messages[0]['content'] += f' Synthetic workload group {(count // 20) % 3}.'
                    request('native', 'soak_rag' if is_rag else 'soak', index, messages)
                    count += 1
                    stop.wait(2)
                report['soak'] = {'elapsed_seconds': time.monotonic()-started,
                                  'pid_start': pid, 'pid_end': server_pid(), 'completed_requests': count + 60}
                save()
        if args.phase in ('all', 'matrix'):
            for mode in ('off', 'hybrid', 'native', 'forced'):
                matrix_mode(mode)
        if args.phase == 'numeric':
            for mode in ('off', 'hybrid', 'native', 'forced'):
                switch(mode)
                messages = quality_messages(0)
                request(mode, 'numeric_prime', 0, messages[:-2], 2048)
                request(mode, 'numeric', 0, messages, 2048)
                request(mode, 'numeric_replay', 0, messages, 2048)
        if args.phase in ('all', 'perf'):
            for pair in range(3):
                orders = (('off', 'hybrid', 'native'), ('native', 'hybrid', 'off'),
                          ('hybrid', 'off', 'native'))
                for mode in orders[pair]:
                    switch(mode)
                    for turn, index in enumerate((0, 14, 15)):
                        messages = quality_messages(index)
                        if turn == 0:
                            request(mode, 'perf_prime', pair, messages[:-2])
                        row = request(mode, 'perf', pair * 3 + turn, messages)
                        row.update(pair=pair, turn=turn)
                        save()
    except BaseException as exc:
        report['errors'].append(type(exc).__name__ + ':' + str(exc))
        raise
    finally:
        stop.set()
        if sampler:
            sampler.join(timeout=10)
        for name, value in original.items():
            try:
                c.set_launch(name, value)
            except Exception as exc:
                report['restoration_errors'].append(name + ':' + type(exc).__name__)
        try:
            deadline = time.monotonic() + 120
            while True:
                try:
                    p.ensure_idle()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            p.write_config(config)
            c.run_command([str(c.MLX), 'restart'])
            p.confirm_profile(p.configured_profile(config))
        except Exception as exc:
            report['restoration_errors'].append('runtime:' + type(exc).__name__)
        report['config_restored'] = p.CONFIG.read_text() == config
        report['launch_restored'] = {name: c.launch_value(name) for name in names} == original
        report['finished_at'] = time.time()
        save()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if report['restoration_errors'] or not report['config_restored'] or not report['launch_restored']:
            raise RuntimeError('Runtime restoration failed; inspect private report')
    return 0 if not report['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
