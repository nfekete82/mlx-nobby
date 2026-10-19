import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_hash_requires_exact_tokens_and_parameters():
    audit = load('hybrid_backend_audit')
    assert audit.digest({'ids': [1, 2], 'temp': 0}) == audit.digest({'temp': 0, 'ids': [1, 2]})
    assert audit.digest([1, 2]) != audit.digest([2, 1])
    with pytest.raises(ValueError):
        audit.digest(float('nan'))


def test_audit_rejects_public_directory_and_symlink(tmp_path):
    audit = load('hybrid_backend_audit')
    tmp_path.chmod(0o755)
    with pytest.raises(RuntimeError, match='0700'):
        audit.emit(tmp_path / 'audit.jsonl', {'safe': True})
    tmp_path.chmod(0o700)
    target = tmp_path / 'target'
    target.write_text('unchanged')
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(OSError):
        audit.emit(link, {'safe': True})
    assert target.read_text() == 'unchanged'
    audit.emit(tmp_path / 'audit.jsonl', {'safe': True})
    assert json.loads((tmp_path / 'audit.jsonl').read_text()) == {'safe': True}
    assert (tmp_path / 'audit.jsonl').stat().st_mode & 0o777 == 0o600


def test_fixture_retrieval_keeps_all_attacks_below_trust_boundary(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    cases = load('hybrid_acceptance_cases')
    assert len(cases.QUALITY) >= 20 and len(cases.ATTACKS) >= 20
    system = None
    for index, attack in enumerate(cases.ATTACKS):
        messages = cases.rag_messages(index)
        assert messages[0]['role'] == 'system'
        assert attack not in messages[0]['content']
        encoded = messages[-1]['content'].split('<LOCAL_KNOWLEDGE_DATA>\n', 1)[1].split('\n</LOCAL_KNOWLEDGE_DATA>', 1)[0]
        assert attack in json.loads(encoded)['sources'][0]
        assert 'AMBER37' in messages[-1]['content']
        assert system is None or messages[0]['content'] == system
        system = messages[0]['content']


def test_full_stream_retains_text_beyond_2048_and_requires_done(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    runner = load('validate-hybrid-acceptance')
    from contextlib import nullcontext
    text = 'x' * 7000
    lines = [b'data: ' + json.dumps({'type': 'content', 'text': text}).encode() + b'\n',
             b'\n', b'event: done\n', b'data: {}\n']
    monkeypatch.setattr(runner.urllib.request, 'urlopen', lambda *a, **k: nullcontext(lines))
    assert runner.stream([], 4096, 'synthetic-test')[0] == text
    monkeypatch.setattr(runner.urllib.request, 'urlopen', lambda *a, **k: nullcontext(lines[:1]))
    with pytest.raises(RuntimeError, match='Incomplete'):
        runner.stream([], 4096, 'synthetic-test')


def test_freed_old_server_swap_cannot_mask_new_workload_growth(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    runner = load('validate-hybrid-acceptance')
    floor = runner.checked_swap_floor(35.2, 23.1)
    assert floor == 23.1
    floor = runner.checked_swap_floor(floor, 22.9)
    assert runner.checked_swap_floor(floor, 23.8) == 22.9
    with pytest.raises(RuntimeError, match='observed minimum'):
        runner.checked_swap_floor(floor, 24.0)


def test_longform_quality_rejects_length_noncompliance_even_with_all_terms():
    cases = load('hybrid_acceptance_cases')
    terms = 'Prefill Cache Decode Streaming throughput '
    assert cases.check_quality(14, terms + 'word ' * 650)['word_count_600_800']
    assert not cases.check_quality(14, terms + 'word ' * 850)['word_count_600_800']
    extended = 'Prefill Cache Decode Streaming speculative throughput '
    assert cases.check_quality(20, extended + 'word ' * 1600)['word_count_1500_1800']
    assert not cases.check_quality(20, extended + 'word ' * 1200)['word_count_1500_1800']


def test_cleanup_waits_for_agent_recovery_and_idle_without_skipping_timeout(monkeypatch):
    from types import SimpleNamespace
    from urllib.error import URLError
    monkeypatch.syspath_prepend(str(SCRIPTS))
    runner = load('validate-hybrid-acceptance')
    clock = [0]
    monkeypatch.setattr(runner, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    outcomes = iter([URLError('Agent restarting'), RuntimeError('busy'), None])
    def ensure_idle():
        outcome = next(outcomes)
        if outcome: raise outcome
    runner.wait_for_idle(SimpleNamespace(ensure_idle=ensure_idle), timeout=3)
    assert clock[0] == 2
    def unavailable(): raise URLError('still restarting')
    with pytest.raises(URLError):
        runner.wait_for_idle(SimpleNamespace(ensure_idle=unavailable), timeout=2)
    assert clock[0] == 4
