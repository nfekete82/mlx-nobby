#!/usr/bin/env python3
"""Private opt-in MLX-VLM 0.6.17 input audit bootstrap; no package edits.

Invoke as a Python executable shim: REAL_PYTHON this_file ORIGINAL_ARGUMENTS.
NOBBY_HYBRID_AUDIT_FILE must point into an owner-only directory. Only digests,
counts and numeric runtime metadata are persisted; never prompt/token contents.
All non-server invocations pass through to the ordinary Python executable.
"""
from __future__ import annotations

import dataclasses
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import threading
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def emit(path, row):
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise RuntimeError('Audit directory must be owned by this user with mode 0700')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError('Audit file must be an owner-only regular file')
        os.write(fd, (json.dumps(row, sort_keys=True) + '\n').encode())
    finally:
        os.close(fd)


def install(path):
    if version('mlx-vlm') != '0.6.17':
        raise RuntimeError('Audit requires mlx-vlm==0.6.17')
    from mlx_vlm.server import generation
    original = generation.ResponseGenerator._log_prefill_started
    current = threading.local()

    def observed(self, request, *, backend):
        info = original(self, request, backend=backend)
        current.request_id = info['request_id']
        ids = request.raw_inputs['input_ids'].tolist()
        args = dataclasses.asdict(request.args)
        emit(path, {'kind': 'backend_input', 'pid': os.getpid(), 'time': time.time(),
                    'request_id': info['request_id'], 'backend': backend,
                    'token_ids_sha256': digest(ids), 'args_sha256': digest(args),
                    'prompt_tokens': request.prompt_tokens,
                    'semantic_hash': request.apc_semantic_hash,
                    'model_sha256': digest(str(self.model_path)),
                    'prefill_step': self._effective_prefill_step_size()})
        return info

    generation.ResponseGenerator._log_prefill_started = observed
    if os.getenv('NOBBY_HYBRID_AUDIT_STATE') == '1':
        # Separate numerical diagnostic, excluded from latency measurements.
        # Transfer one layer at a time; never retain a second complete cache.
        prefill = generation._run_chunked_speculative_prefill

        def state_digest(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return [state_digest(item) for item in value]
            if isinstance(value, dict):
                return {key: state_digest(item) for key, item in value.items()}
            import mlx.core as mx
            import numpy as np
            # float16/bfloat16 -> float32 is exact; values remain private.
            array = np.asarray(value.astype(mx.float32))
            if not np.isfinite(array).all():
                raise RuntimeError('Non-finite prefill state')
            return {'shape': list(array.shape), 'dtype': str(value.dtype),
                    'values_sha256': hashlib.sha256(array.tobytes()).hexdigest()}

        def numerical(*args, **kwargs):
            result = prefill(*args, **kwargs)
            states = [state_digest(layer.state) for layer in args[3]]
            emit(path, {'kind': 'prefill_state', 'pid': os.getpid(), 'time': time.time(),
                        'request_id': current.request_id, 'layers': len(states),
                        'cache_sha256': digest(states),
                        'logits_sha256': digest(state_digest(result[0].logits))})
            return result

        generation._run_chunked_speculative_prefill = numerical
    decode = generation.ResponseGenerator._log_decode_progress

    def finished(uid, info, **kwargs):
        result = decode(uid, info, **kwargs)
        if kwargs.get('finish_reason'):
            import mlx.core as mx
            emit(path, {'kind': 'backend_finish', 'pid': os.getpid(),
                        'time': time.time(), 'request_id': info.get('request_id'),
                        'finish_reason': kwargs['finish_reason'],
                        'generated_tokens': info.get('generated_tokens'),
                        'metal_active_bytes': mx.get_active_memory(),
                        'metal_cache_bytes': mx.get_cache_memory(),
                        'metal_peak_bytes': mx.get_peak_memory()})
        return result

    generation.ResponseGenerator._log_decode_progress = staticmethod(finished)


def main():
    args = sys.argv[1:]
    module_server = args[:3] == ['-m', 'mlx_vlm', 'server']
    hybrid_server = bool(args and Path(args[0]).name == 'hybrid_apc_dflash_runtime.py'
                         and args[1:3] == ['mlx_vlm', 'server'])
    if not (module_server or hybrid_server):
        os.execv(sys.executable, [sys.executable, *args])
    path = Path(os.environ['NOBBY_HYBRID_AUDIT_FILE'])
    install(path)
    if hybrid_server:
        sys.path.insert(0, str(Path(args[0]).resolve().parent))
        sys.argv = args
        runpy.run_path(args[0], run_name='__main__')
    else:
        sys.argv = ['mlx_vlm', *args[2:]]
        runpy.run_module('mlx_vlm', run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
