import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / "scripts/benchmark-chat-cache-causal.py"
    spec = importlib.util.spec_from_file_location("hybrid_causal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_causal_modes_and_summary():
    m = module()
    assert [case[0] for case in m.CASES] == ["off", "split_only", "on"]
    rows = []
    for name, hits, matched, chars in [
        ("off", 0, 0, 1805),
        ("split_only", 0, 0, 1370),
        ("on", 1, 725, 1370),
    ]:
        rows.append({"mode": name, "turns": [
            {"answer_chars": chars, "delta_exact_hits": 0},
            {},
            {"delta_exact_hits": hits, "delta_matched_tokens": matched},
        ]})
    summary = m.compare_case_rows(rows)
    assert summary["split_only"]["first_turn_exact_hits"] == 0
    assert summary["on"]["third_turn_matched_tokens"] == 725


def test_compare_first_turn_content_without_leaking_text(tmp_path):
    m = module()
    rows = []
    for mode, content in [
        ("off", "One full answer"),
        ("split_only", "Short"),
        ("on", "Short"),
    ]:
        path = tmp_path / (mode + ".json")
        path.write_text(json.dumps({"answers": [
            {"turn": n, "question": "q" + str(n),
             "answer": content if n == 1 else "response"}
            for n in (1, 2, 3)]}))
        rows.append({"mode": mode, "answers_file": str(path)})
    result = m.compare_answers(rows)
    assert result["off_vs_split_only"]["first_turn_exact_equal"] is False
    assert result["split_only_vs_on"]["first_turn_exact_equal"] is True
    assert "One full answer" not in json.dumps(result)


def test_runtime_keeps_split_boundary_without_store():
    source = (ROOT / "scripts/hybrid_apc_dflash_runtime.py").read_text()
    assert 'NOBBY_HYBRID_EARLY_CHECKPOINT_STORE' in source
    assert 'Hybrid early checkpoint split-only' in source
    assert source.index('if hybrid_early_boundary is not None and hybrid_consumed == hybrid_early_boundary:') < source.index('NOBBY_HYBRID_EARLY_CHECKPOINT_STORE')


def test_failure_restores_every_tracked_setting_and_restarts(monkeypatch, tmp_path):
    import subprocess
    import pytest
    m = module()
    original = {m.FEATURE: '', m.STORE: '0', m.DIAG: '', m.ALIGN: '1',
                m.SLOTS: '2', m.PREFILL: '1024'}
    calls, commands = [], []
    monkeypatch.setattr(m, 'launch_value', lambda key: original[key])
    monkeypatch.setattr(m, 'set_launch', lambda key, value: calls.append((key, value)))
    monkeypatch.setattr(m.runpy, 'run_path', lambda path: {
        'ensure_idle': lambda: None, 'confirm_profile': lambda mode: None})
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(m, 'verify_prefill_in_server_process', lambda step: None)
    monkeypatch.setattr(m, 'memory_snapshot', lambda: {})
    def fail_benchmark(command):
        commands.append(command)
        if str(m.BENCH) in command:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(m, 'run_command', fail_benchmark)
    with pytest.raises(subprocess.CalledProcessError):
        m.main(['--confirm-restarts', '--compare-native', '--fixed-history',
                '--capture-answers', '--diagnose', '--prefill-step', '256',
                '--output', str(tmp_path / 'report.json')])
    assert dict(calls[-len(original):]) == original
    assert commands[-1] == [str(m.MLX), 'restart']


def test_all_turn_hash_comparison_detects_cache_hit_divergence():
    m = module()
    rows = [{'mode': mode, 'turns': [
        {'request_sha256': str(i), 'answer_sha256': str(i)} for i in range(3)]}
        for mode in ('baseline1', 'native2')]
    rows[1]['turns'][2]['answer_sha256'] = 'changed'
    comparison = m.compare_request_and_response_hashes(rows)['native2']
    assert all(row['client_request_equal'] for row in comparison)
    assert [row['answer_exact_equal'] for row in comparison] == [True, True, False]
