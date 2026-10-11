"""Offline checks for honest scoring and safe benchmark admission/output."""
import json
from pathlib import Path

import pytest

from agent import v15_quality_benchmark as benchmark


def test_missing_invalid_and_refused_predictions_are_not_quality_success():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    cases = data['cases']
    missing = benchmark.score_cases(cases, {})
    assert missing['errors'] == len(cases)
    assert missing['accuracy'] == missing['supported_recall'] == 0
    refused = benchmark.score_cases(cases, {c['id']: {'status': 'not_checked'} for c in cases})
    assert refused['checked_coverage'] == refused['supported_recall'] == 0
    assert refused['accuracy'] == 1 / 64
    falsely_supported = benchmark.score_cases(cases, {c['id']: {'status': 'supported'} for c in cases})
    assert falsely_supported['supported_precision'] == 18 / 64
    assert falsely_supported['accuracy'] < .5
    invalid = benchmark.score_cases(cases, {c['id']: {'status': 'true'} for c in cases})
    assert invalid['errors'] == 64


def test_frozen_bundle_does_not_admit_failed_rss_or_private_source_fixtures():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    wanted = {'timeout', 'rate-limit', 'captcha', 'cancelled', 'rss-availability', 'private-target'}
    cases = [c for c in data['cases'] if c['id'] in wanted]
    bundle = benchmark.fixture_bundle(data, cases)
    assert not bundle.facts
    assert all(s.retrieval_status == 'unusable' for s in bundle.sources)
    assert not any(s.domain in {'127.0.0.1', 'localhost'} for s in bundle.sources)


def test_frozen_bundle_ignores_spoofed_publisher_and_keeps_exact_anchors():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    bundle = benchmark.fixture_bundle(data, [c for c in data['cases'] if c['id'] == 'fake-official'])
    assert bundle.sources[0].publisher == 'example.org'
    assert bundle.sources[0].authority == 'unassessed'
    fact = bundle.facts[0]
    start, end = fact.source_location
    assert bundle.sources[0].text[start:end] == fact.evidence_excerpt


@pytest.mark.parametrize('mutation', ['duplicate', 'unknown_source', 'invalid_gold', 'mixed_date'])
def test_dataset_errors_are_rejected_before_native_import(tmp_path, mutation):
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    if mutation == 'duplicate':
        data['cases'].append(data['cases'][0])
    elif mutation == 'unknown_source':
        data['cases'][0]['source_ids'] = ['invented']
    elif mutation == 'invalid_gold':
        data['cases'][0]['expected_status'] = 'verified_true'
    else:
        data['cases'][0]['as_of'] = '2099-01-01'
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        benchmark.load_dataset(path)


@pytest.mark.parametrize('existing', ['report', 'raw'])
def test_existing_outputs_are_preserved_and_model_is_never_called(tmp_path, monkeypatch, existing):
    report, raw = tmp_path / 'report.json', tmp_path / 'raw.jsonl'
    target = report if existing == 'report' else raw
    target.write_text('preserve this user artifact')
    def forbidden(*args, **kwargs):
        pytest.fail('Model/app must not be imported before exclusive destinations are opened')
    monkeypatch.setattr(benchmark, 'guarded_native_llm', forbidden)
    with pytest.raises(FileExistsError):
        benchmark.main(['--output', str(report), '--raw-output', str(raw)])
    assert target.read_text() == 'preserve this user artifact'


def test_same_output_paths_are_rejected_before_opening(tmp_path):
    output = tmp_path / 'report.json'
    with pytest.raises(SystemExit):
        benchmark.main(['--output', str(output), '--raw-output', str(output)])
    assert not output.exists()


def test_actual_verifier_batch_receives_no_human_gold_and_keeps_case_sources_separate():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    data = {**data, 'cases': [data['cases'][0], data['cases'][4]]}
    prompts = []
    def model(purpose, prompt, max_tokens):
        prompts.append(prompt)
        payload = json.loads(prompt.rsplit('\n', 1)[1])
        assert purpose == 'agent.verify'
        assert len(payload['claims']) == 2
        assert 'expected_status' not in prompt
        assert 'rationale' not in prompt
        assert payload['claims'][0]['passage_ids'] == ['nasa-passage']
        assert payload['claims'][1]['passage_ids'] == ['python-passage']
        return json.dumps({'claims': [
            {'id': c['id'], 'status': 'supported', 'reason': 'Mocked model response for orchestration test.',
             'passage_ids': c['passage_ids']} for c in payload['claims']]})
    report = benchmark.run_benchmark(data, model)
    assert len(prompts) == 1
    assert report['cases'] == 2
    assert report['errors'] == 0
    assert report['independent_truth_verification'] is False
    assert report['batches'][0]['case_ids'] == ['astronomy-1', 'software-python-1']


def test_provider_failures_count_as_missing_predictions_not_human_not_checked_matches():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    data = {**data, 'cases': data['cases'][:2]}
    def unavailable(*args):
        raise RuntimeError('secret configuration string must not be logged')
    records = []
    report = benchmark.run_benchmark(data, unavailable, emit=records.append)
    assert report['errors'] == 2
    assert report['accuracy'] == 0
    assert records[0]['error_type'] == 'RuntimeError'
    assert 'secret configuration' not in json.dumps(records)


@pytest.mark.parametrize('size', [0, 9, True])
def test_verifier_batches_are_bounded_before_model_calls(size):
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    def forbidden(*args):
        pytest.fail('Invalid batch must not reach model')
    with pytest.raises(ValueError):
        benchmark.run_benchmark(data, forbidden, batch_size=size)


def test_invalid_model_protocol_never_matches_human_subjective_not_checked():
    data, _ = benchmark.load_dataset(benchmark.DEFAULT_DATASET)
    subjective = next(c for c in data['cases'] if c['id'] == 'opinion')
    result = benchmark.score_cases([subjective], {'opinion': {
        'status': 'not_checked', 'decision_origin': 'invalid_response'}})
    assert result['errors'] == 1
    assert result['correct'] == 0
    genuine = benchmark.score_cases([subjective], {'opinion': {
        'status': 'not_checked', 'decision_origin': 'model'}})
    assert genuine['correct'] == 1


def test_native_import_rejects_user_home_and_nonempty_scratch(tmp_path, monkeypatch):
    actual = tmp_path / 'actual-home'
    actual.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: actual))
    with pytest.raises(ValueError, match='differ'):
        with benchmark.guarded_native_llm(lambda item: None, scratch_home=actual):
            pytest.fail('User home must never become native benchmark state')
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    artifact = scratch / 'existing-user-artifact'
    artifact.write_text('preserved')
    with pytest.raises(ValueError, match='new or empty'):
        with benchmark.guarded_native_llm(lambda item: None, scratch_home=scratch):
            pytest.fail('Existing scratch data must not be imported by app workers')
    assert artifact.read_text() == 'preserved'
