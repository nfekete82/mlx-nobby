"""Opt-in in-process hybrid APC diagnostics. Never prints token IDs or content.

Maintains only one bounded copy of token IDs in process RAM while enabled, to
compare consecutive checkpoints. Disabled by default, no disk persistence.
"""
from __future__ import annotations
import logging
import os
import threading

LOG = logging.getLogger("nobby.hybrid.apc")
ENV = "NOBBY_HYBRID_CACHE_DIAG"
MAX_IDS = 65536
_lock = threading.Lock()
_previous = None


def classify(ids, semantic_hash, *, matched_tokens, minimum_tokens, guard_tokens,
             stored=False, checkpoint_tokens=None):
    """Emit safe numeric metadata and a reason, without exposing tokens."""
    global _previous
    if os.environ.get(ENV) != "1":
        return None
    count = len(ids)
    checkpoint = (max(0, count - guard_tokens) if checkpoint_tokens is None
                  else max(0, min(count - guard_tokens, checkpoint_tokens)))
    with _lock:
        previous = _previous
        common = 0
        semantic_same = None
        if previous is not None:
            prior_ids, prior_hash = previous
            semantic_same = prior_hash == semantic_hash
            for a, b in zip(prior_ids, ids):
                if a != b:
                    break
                common += 1

        if count > MAX_IDS:
            reason = "too_long_to_track"
            _previous = None
        elif checkpoint < minimum_tokens:
            reason = "below_minimum"
        elif matched_tokens > 0:
            reason = "exact_hit"
        elif previous is None:
            reason = "no_previous_snapshot"
        elif not semantic_same:
            reason = "semantic_hash_changed"
        elif common < minimum_tokens:
            reason = "token_prefix_changed"
        elif common < len(previous[0]):
            reason = "prefix_shorter_than_checkpoint"
        else:
            reason = "lookup_miss_despite_matching_prefix"

        # Only a successful store updates the tracked snapshot; no false
        # attribution from attempted/failed stores.
        if stored and checkpoint >= minimum_tokens and count <= MAX_IDS:
            _previous = (tuple(int(x) for x in ids[:checkpoint]), semantic_hash)
        LOG.info(
            "HYBRID_APC_DIAG reason=%s prompt_tokens=%d checkpoint_tokens=%d "
            "matched_tokens=%d common_prefix_tokens=%d previous_tokens=%d "
            "semantic_hash_same=%s stored=%s",
            reason, count, checkpoint, matched_tokens, common,
            len(previous[0]) if previous else 0, semantic_same, stored,
        )
        return reason
