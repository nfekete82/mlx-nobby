from pathlib import Path
import json
import threading

import pytest
from agent import model_scout_routes as scout


def test_ornith_discovery_handles_mixed_quantization():
    name = 'mlx-works/Ornith-1.5-35B-A3B-oQ4e-mtp'
    assert scout.infer_quantization_bits(name) == 4
    assert scout.infer_role(name) == 'coding'
    assert scout.estimate_memory_gb(35, 4) < 48


def test_metadata_without_weights_cannot_start_benchmark(tmp_path):
    model = {'repo': str(tmp_path), 'available': True}
    (tmp_path / 'config.json').write_text('{}')
    assert scout.complete_local_model(model) is None
    (tmp_path / 'tokenizer.json').write_text('{}')
    (tmp_path / 'tokenizer_config.json').write_text('{}')
    (tmp_path / 'model.safetensors').write_bytes(b'fixture')
    assert scout.complete_local_model(model) == tmp_path
    index = tmp_path / 'model.safetensors.index.json'
    index.write_text(json.dumps({'weight_map': {'x': 'missing.safetensors'}}))
    assert scout.complete_local_model(model) is None
    index.write_text('broken')
    assert scout.complete_local_model(model) is None


def test_scout_restores_baseline_when_switch_fails(monkeypatch, tmp_path):
    models = [{'alias':'baseline','repo':'local/baseline'}, {'alias':'candidate','repo':'local/candidate'}]
    monkeypatch.setattr(scout, 'complete_local_model', lambda _: tmp_path)
    monkeypatch.setattr(scout, '_runtime_model_id', lambda _: 'local/baseline')
    monkeypatch.setattr(scout, 'benchmark_runtime', lambda *a, **kw: {'performance': {}, 'quality': {}})
    monkeypatch.setattr(scout, '_BENCHMARK_JOBS', {'job': {'id':'job'}})
    switches = []
    def switch(alias):
        switches.append(alias)
        if alias == 'candidate':
            raise RuntimeError('synthetic partial switch failure')
    scout._run_benchmark_job_inner('job', 'candidate', lambda: models,
        lambda: {'MODEL':'local/baseline','PORT':8000}, switch, threading.RLock(), lambda _: None, 'coding')
    assert switches == ['candidate', 'baseline']
    assert scout._BENCHMARK_JOBS['job']['status'] == 'failed'


def test_coding_suite_request_is_opt_in():
    assert scout.BenchmarkRequest(candidate_alias='candidate').suite == 'quick'
    assert scout.BenchmarkRequest(candidate_alias='candidate', suite='coding').suite == 'coding'
    with pytest.raises(ValueError):
        scout.BenchmarkRequest(candidate_alias='candidate', suite='unknown')
