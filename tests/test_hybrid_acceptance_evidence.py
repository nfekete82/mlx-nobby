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
        assert attack in messages[-1]['content']
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
