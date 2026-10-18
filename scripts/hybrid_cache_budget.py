"""Conservative tensor-payload admission budget for hybrid exact snapshots.

This bounds retained tensor payload plus one pending clone, not process RSS or
Metal allocator overhead. Unknown layouts skip storage; inference continues.
"""
from __future__ import annotations

import logging
import os

LOG = logging.getLogger('nobby.hybrid.budget')
DEFAULT_MIB = 1024


def budget_bytes():
    raw = os.getenv('NOBBY_HYBRID_CACHE_MAX_MIB', str(DEFAULT_MIB))
    if not raw.isascii() or not raw.isdecimal() or not 64 <= int(raw) <= 8192:
        raise ValueError('NOBBY_HYBRID_CACHE_MAX_MIB must be 64..8192')
    return int(raw) * 1024 * 1024


def tensor_bytes(value):
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return sum(tensor_bytes(item) for item in value)
    if isinstance(value, dict):
        return sum(tensor_bytes(item) for item in value.values())
    size = getattr(value, 'nbytes', None)
    if type(size) is not int or size < 0:
        raise ValueError('Unknown cache tensor payload')
    return size


def cache_bytes(cache):
    return sum(tensor_bytes(layer.state) for layer in cache)


def store(manager, token_ids, prompt_cache, *, extra_hash=0):
    try:
        incoming = cache_bytes(prompt_cache)
        # Upstream's resident_bytes counts only the block pool, not exact
        # snapshots. Inspect the guarded 0.6.17 layout under its own lock.
        with manager.lock:
            retained = sum(cache_bytes(entry.prompt_cache)
                           for entry in manager._exact_cache.values())
        budget = budget_bytes()
        if retained + incoming > budget:
            LOG.warning('Hybrid snapshot skipped: retained_bytes=%d incoming_bytes=%d budget_bytes=%d',
                        retained, incoming, budget)
            return False
        saved = manager.store_exact_cache(token_ids, prompt_cache, extra_hash=extra_hash)
        LOG.info('HYBRID_APC_MEMORY saved=%s retained_before_bytes=%d snapshot_bytes=%d budget_bytes=%d',
                 saved, retained, incoming, budget)
        return saved
    except Exception:
        LOG.warning('Hybrid snapshot admission failed; skipping cache store', exc_info=True)
        return False
