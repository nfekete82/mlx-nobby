"""Real SQLite pipeline guards for ambiguous extractor fields; fictional data."""
import json
import pytest
from agent import personal_memory as pm, semantic_personal_memory as smart
from agent import knowledge_memory as km, memory_dashboard


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, 'DB_PATH', tmp_path/'claims.sqlite3')
    monkeypatch.setattr(memory_dashboard, 'STATE_PATH', tmp_path/'control.json')
    pm.set_enabled(True)
    smart.set_enabled(True)


def save(cid, text, value, field='status', kind='statement'):
    output = json.dumps({'facts':[dict(subject='ich', field=field, value=value,
        evidence=text, confidence=.99, correction=False, kind=kind)], 'episodes':[]})
    return smart.apply(cid, 0, text, output)


def test_status_domains_coexist_but_same_domain_conflicts():
    save('fictional-career', 'Beruflich bin ich selbstständig.', 'selbstständig')
    save('fictional-health', 'Gesundheitlich bin ich beschwerdefrei.', 'beschwerdefrei')
    assert {r['field'] for r in pm.list_facts()} == {'status.beruflich','status.gesundheitlich'}
    assert pm.list_conflicts() == []
    save('fictional-conflict', 'Beruflich bin ich angestellt.', 'angestellt')
    assert len(pm.list_conflicts()) == 1
    assert pm.list_conflicts()[0]['proposed_value'] == 'angestellt'
    with pm._connect() as conn:
        assert conn.execute('SELECT count(*) FROM fact_evidence').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM conflict_evidence').fetchone()[0] == 1


def test_temporal_claims_and_plans_do_not_change_current_state():
    save('fictional-current', 'Beruflich bin ich selbstständig.', 'selbstständig')
    save('fictional-past', 'Im Jahr 2021 war ich beruflich arbeitslos.', 'arbeitslos')
    save('fictional-plan', 'Ich plane beruflich angestellt zu werden.', 'angestellt',kind='plan')
    assert len(pm.list_facts()) == 3
    assert pm.list_conflicts() == []
    fields = {r['field'] for r in pm.list_facts()}
    assert 'status.beruflich.vergangen.2021' in fields
    assert 'status.beruflich.plan' in fields
    save('fictional-past-conflict', 'Im Jahr 2021 war ich beruflich angestellt.', 'angestellt')
    assert len(pm.list_conflicts()) == 1
    recall = km.context('Wie war mein beruflicher Status 2021?')
    assert 'arbeitslos' in recall and 'fictional-past' in recall
    assert 'historical source assertion' in recall


def test_unknown_status_does_not_hide_conflicts_and_legacy_is_untouched():
    pm.create_fact('ich','status','unbekannt')
    save('fictional-generic', 'Mein Status ist bereit.', 'bereit')
    assert len(pm.list_conflicts()) == 1
    save('fictional-health', 'Gesundheitlich bin ich beschwerdefrei.', 'beschwerdefrei')
    assert any(r['field']=='status' and r['value']=='unbekannt' for r in pm.list_facts())
    assert len(pm.list_conflicts()) == 1
    assert 'beschwerdefrei' in km.context('Wie ist mein gesundheitlicher Status?')
    assert 'beschwerdefrei' not in km.context('Welchen Status hat das Python-Projekt?')


def test_since_dates_do_not_split_current_conflict_identity():
    save('fictional-since', 'Seit 2024 bin ich beruflich selbstständig.', 'selbstständig')
    save('fictional-since-two', 'Seit 2025 bin ich beruflich angestellt.', 'angestellt')
    assert len(pm.list_facts()) == 1
    assert len(pm.list_conflicts()) == 1


def test_model_status_suffixes_cannot_hide_a_true_conflict():
    save('fictional-a', 'Beruflich bin ich selbstständig.', 'selbstständig',field='status.random_a')
    save('fictional-b', 'Beruflich bin ich angestellt.', 'angestellt',field='status.random_b')
    assert len(pm.list_facts()) == 1
    assert len(pm.list_conflicts()) == 1


def test_correction_wording_is_not_a_historical_period():
    assert smart.claim_field('geburtstag', 'Mein Geburtstag war falsch, richtig ist der 02.03.1990.', 'statement') == 'geburtstag'
