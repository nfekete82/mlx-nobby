import importlib.util
from pathlib import Path
from types import SimpleNamespace
from threading import Lock


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts/hybrid_cache_budget.py'
    spec = importlib.util.spec_from_file_location('hybrid_budget_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cache(size):
    return [SimpleNamespace(state=[None, SimpleNamespace(nbytes=size)])]


class Manager:
    def __init__(self, retained):
        self.lock = Lock()
        self._exact_cache = {1: SimpleNamespace(prompt_cache=cache(retained))}
        self.stores = []

    def store_exact_cache(self, ids, value, *, extra_hash):
        self.stores.append((tuple(ids), value, extra_hash))
        return True


def test_admission_accounts_for_retained_exact_state_and_pending_clone(monkeypatch):
    monkeypatch.setenv('NOBBY_HYBRID_CACHE_MAX_MIB', '64')
    m = load()
    manager = Manager(63 * 1024**2)
    assert not m.store(manager, [1, 2], cache(2 * 1024**2), extra_hash=7)
    assert manager.stores == []
    assert m.store(manager, [1, 2], cache(1024**2), extra_hash=7)
    assert manager.stores[0][0] == (1, 2)
    assert manager.stores[0][2] == 7


def test_unknown_state_cannot_trigger_unbudgeted_store():
    manager = Manager(0)
    assert not load().store(manager, [1], [SimpleNamespace(state=object())])
    assert manager.stores == []


def test_budget_configuration_is_bounded(monkeypatch):
    import pytest
    m = load()
    monkeypatch.delenv('NOBBY_HYBRID_CACHE_MAX_MIB', raising=False)
    assert m.budget_bytes() == 1024**3
    for value in ('0', '63', '8193', 'NaN', '-1', '1.5', '１２８'):
        monkeypatch.setenv('NOBBY_HYBRID_CACHE_MAX_MIB', value)
        with pytest.raises(ValueError):
            m.budget_bytes()


def test_store_failure_leaves_inference_cache_untouched():
    manager = Manager(0)
    def fail(*args, **kwargs):
        raise RuntimeError('clone failed')
    manager.store_exact_cache = fail
    value = cache(128)
    assert not load().store(manager, [1], value)
    assert value[0].state[1].nbytes == 128
