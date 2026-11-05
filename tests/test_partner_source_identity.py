"""Narrow source-grounded partner identity correction; fictional data only."""
import json
import pytest
from agent import personal_memory as pm, semantic_personal_memory as smart
from agent import memory_dashboard, knowledge_memory as km

TEXT = 'Meine Partnerin heißt Elara und arbeitet als Lehrerin.'


def output(text=TEXT, subject='personen.elara', value='Lehrerin', confidence=.99):
    return json.dumps({'facts':[dict(subject=subject, field='beruf', value=value,
        evidence=text, confidence=confidence, correction=False)], 'episodes':[]})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, 'DB_PATH', tmp_path/'personal.sqlite3')
    monkeypatch.setattr(memory_dashboard, 'STATE_PATH', tmp_path/'control.json')
    pm.set_enabled(True)
    smart.set_enabled(True)


@pytest.mark.parametrize('text', [TEXT, 'Mein Partner heißt Elara und arbeitet als Lehrerin.'])
def test_explicit_partner_name_and_attribute_keep_original_source(text):
    smart.apply('fictional-partner',0,text,output(text))
    assert {(r['subject'],r['field'],r['value']) for r in pm.list_facts()} == {
        ('partner','name','Elara'), ('partner','beruf','Lehrerin')}
    with pm._connect() as conn:
        quotes = conn.execute('SELECT evidence FROM fact_evidence').fetchall()
        assert len(quotes)==2 and all(r[0]==text for r in quotes)
    recall = km.context('Wie heißt meine Partnerin und welchen Beruf hat sie?')
    assert 'Elara' in recall and 'Lehrerin' in recall and 'chat fictional-partner message 0' in recall


@pytest.mark.parametrize('role', ['Kollegin','Freundin','Bekannte'])
def test_other_named_people_do_not_become_partner(role):
    text=f'Meine {role} heißt Elara und arbeitet als Lehrerin.'
    rows=smart.parse_facts(output(text),text)
    assert len(rows)==1 and rows[0]['subject']=='personen.elara'


def test_same_name_in_another_clause_is_not_an_alias():
    text='Meine Partnerin heißt Elara und meine Kollegin Elara arbeitet als Lehrerin.'
    rows=smart.parse_facts(output(text),text)
    assert any(r['subject']=='personen.elara' and r['field']=='beruf' for r in rows)
    assert not any(r['subject']=='partner' and r['field']=='beruf' for r in rows)


@pytest.mark.parametrize('text', [
    'Wenn meine Partnerin Elara heißt, wäre sie Lehrerin.',
    'Meine Partnerin heißt Elara und arbeitet als Lehrerin?',
    '"Meine Partnerin heißt Elara und arbeitet als Lehrerin."',
    'Meine Partnerin heißt Elara und arbeitet nicht als Lehrerin.',
])
def test_unsafe_assertions_do_not_synthesize_partner_names(text):
    assert not any(r['subject']=='partner' for r in smart.parse_facts(output(text),text))


def test_low_confidence_and_invented_properties_remain_rejected():
    for raw in (output(confidence=.5),output(value='Pilotin')):
        rows=smart.parse_facts(raw,TEXT)
        assert [(r['subject'],r['field'],r['value']) for r in rows]==[('partner','name','Elara')]


def test_existing_conflict_delete_and_pause_guards_still_apply():
    smart.apply('fictional-first',0,TEXT,output())
    changed='Meine Partnerin heißt Elara und arbeitet als Pilotin.'
    smart.apply('fictional-second',0,changed,output(changed,value='Pilotin'))
    assert len(pm.list_conflicts())==1
    for row in pm.list_facts():
        pm.delete_fact(row['id'])
    smart.apply('fictional-third',0,TEXT,output())
    assert pm.list_facts()==[]
    memory_dashboard.set_paused(True)
    assert smart.apply('fictional-paused',0,TEXT,output())['action']=='disabled'
