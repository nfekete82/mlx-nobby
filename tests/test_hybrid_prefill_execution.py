"""Execute the injected prefill segment with a stateful CPU cache model."""
import importlib.util
import logging
import textwrap
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Tensor:
    def __init__(self, length):
        self.shape = (1, length)

    def __getitem__(self, index):
        part = index[1]
        return Tensor(len(range(*part.indices(self.shape[1]))))


class Manager:
    exact_cache_guard_tokens = 16
    exact_cache_min_tokens = 16

    def __init__(self, matched=0, broken=False):
        self.matched, self.broken = matched, broken
        self.saved = []
        self.lookup_args = None

    def lookup_exact_cache(self, ids, **kwargs):
        self.lookup_args = kwargs
        if self.broken:
            raise RuntimeError('lookup failure')
        return ([SimpleNamespace(state=self.matched)] if self.matched else None,
                self.matched)

    def store_exact_cache(self, ids, cache, *, extra_hash):
        self.saved.append((len(ids), cache[0].state, extra_hash))
        return True


def execute(manager):
    calls = []
    cold = [SimpleNamespace(state=0)]
    def forward(ids, *, cache, **kwargs):
        calls.append(ids.shape[1])
        cache[0].state += ids.shape[1]
    request = SimpleNamespace(apc_semantic_hash=17, images=[], audio=[], videos=[], raw_inputs={})
    scope = {
        'B': 1, 'draft_kind': 'dflash',
        'self': SimpleNamespace(apc_manager=manager, apc_mode='exact'),
        'prefill_step_size': 256, 'pending': [request],
        'all_input_ids': [list(range(1002))],
        'prompt_cache': cold, 'prompt_kwargs': {},
        'inputs_embeds_mx': Tensor(1002), 'input_mx': Tensor(1002),
        'time': SimpleNamespace(perf_counter=lambda: 0),
        'logger': logging.getLogger(__name__), 'nobby_hybrid_diag': None,
        'nobby_checkpoint_policy': load('hybrid_checkpoint_policy'),
        'nobby_hybrid_early_store': True,
        'nobby_hybrid_cache_budget': SimpleNamespace(store=lambda m, *args, **kw: m.store_exact_cache(*args, **kw)),
        '_sequence_aligned_prefill_keys': lambda *a, **k: (),
        '_drop_prefill_kwargs': lambda value, *a: value,
        '_slice_prefill_kwargs': lambda value, *a: value,
        'mx': SimpleNamespace(stream=lambda _: nullcontext(), eval=lambda _: None, clear_cache=lambda: None),
        'generation_stream': None, 'lm': forward,
    }
    source = load('hybrid_apc_dflash_runtime').PREFILL_ADAPTER
    source = source.rsplit('                out, input_mx = _run_chunked_speculative_prefill(', 1)[0]
    exec(textwrap.dedent(source), scope)
    return calls, scope


def test_native_snapshot_does_not_add_forward_calls(monkeypatch):
    monkeypatch.delenv('NOBBY_HYBRID_EARLY_CHECKPOINT', raising=False)
    baseline, _ = execute(Manager(324))
    monkeypatch.setenv('NOBBY_HYBRID_EARLY_CHECKPOINT', '1')
    monkeypatch.setenv('NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE', '1')
    manager = Manager(324)
    native, scope = execute(manager)
    assert native == baseline == [256, 256, 150]
    assert manager.saved == [(580, 580, 17), (986, 986, 17)]
    assert scope['input_mx'].shape[1] == 16


def test_forced_boundary_changes_forward_segmentation(monkeypatch):
    monkeypatch.setenv('NOBBY_HYBRID_EARLY_CHECKPOINT', '1')
    monkeypatch.setenv('NOBBY_HYBRID_EARLY_CHECKPOINT_ALIGN_NATIVE', '0')
    manager = Manager(324)
    calls, _ = execute(manager)
    assert calls == [256, 246, 160]
    assert manager.saved == [(826, 826, 17), (986, 986, 17)]


def test_lookup_failures_and_invalid_offsets_recompute_cold(monkeypatch):
    monkeypatch.delenv('NOBBY_HYBRID_EARLY_CHECKPOINT', raising=False)
    for manager in (Manager(broken=True), Manager(990), Manager(-1), Manager('bad')):
        calls, scope = execute(manager)
        assert calls == [256, 256, 256, 218]
        assert scope['hybrid_matched_tokens'] == 0
        assert manager.lookup_args == {'extra_hash': 17, 'max_prefix_tokens': 986}
        assert manager.saved == [(986, 986, 17)]
