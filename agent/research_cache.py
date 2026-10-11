"""Bounded request-scoped reuse of public search/fetch observations.

No cross-request state, disk persistence, or authority decisions live here.
Tool permission and cancellation checks still run before the adapters execute.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import inspect
import json

_cache = ContextVar("research_observation_cache", default=None)
MAX_ENTRIES = 32
MAX_BYTES = 512_000


@contextmanager
def request_research_cache():
    token = _cache.set({"entries": {}, "bytes": 0})
    try:
        yield
    finally:
        _cache.reset(token)


def reuse_research_observation(function):
    """Reuse identical completed observations, including failure diagnostics."""
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        state = _cache.get()
        if state is None:
            return function(*args, **kwargs)
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        key = (function.__name__, json.dumps(arguments.arguments, sort_keys=True))
        if key in state["entries"]:
            result = deepcopy(state["entries"][key])
            result["reused_observation"] = True
            return result
        result = function(*args, **kwargs)
        if isinstance(result, dict) and len(state["entries"]) < MAX_ENTRIES:
            size = len(key[1].encode("utf-8")) + len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if state["bytes"] + size <= MAX_BYTES:
                state["entries"][key] = deepcopy(result)
                state["bytes"] += size
        return result
    return wrapped
