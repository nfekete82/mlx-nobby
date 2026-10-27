"""Brief, bounded reuse of identical classifier inputs within one traced turn.

This caches only raw classifier output. Dispatch, workspace selection, media
intent, manager arbitration and permission gates still run on every request.
"""

from collections import OrderedDict
import hashlib
import json
import os
import threading
import time


class RouterTurnCache:
    def __init__(self, *, ttl=5.0, capacity=128, clock=time.monotonic):
        self.ttl = ttl
        self.capacity = capacity
        self.clock = clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def classify(self, trace_id, inputs, generate, *, validate=None):
        if not trace_id or os.getenv("MLX_ROUTER_TURN_REUSE", "1").strip().lower() in {"0", "false", "off", "no"}:
            return generate()
        digest = hashlib.sha256(json.dumps(
            inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).digest()
        key = (trace_id, digest)
        now = self.clock()
        with self.lock:
            for expired in [k for k, (until, _) in self.entries.items() if until <= now]:
                del self.entries[expired]
            cached = self.entries.get(key)
            if cached is not None:
                self.entries.move_to_end(key)
                return cached[1]

        # No cache lock across inference. Failures and oversized responses are
        # not retained; concurrent misses may independently classify safely.
        result = generate()
        if (isinstance(result, str) and len(result.encode("utf-8")) <= 8192
                and (validate is None or validate(result))):
            with self.lock:
                self.entries[key] = (self.clock() + self.ttl, result)
                self.entries.move_to_end(key)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
        return result


turn_classifier_cache = RouterTurnCache()
