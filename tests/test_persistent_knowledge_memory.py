"""Synthetic acceptance of the extended local memory data flow. No real user data."""
import json
import queue
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import knowledge_memory as km, memory_commands as commands
from agent import personal_memory as pm, semantic_personal_memory as smart
from agent import memory_dashboard, memory, chat_archive, memory_embeddings
from agent.knowledge_memory_routes import install_routes


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, 'DB_PATH', tmp_path / 'personal.sqlite3')
    monkeypatch.setattr(memory, 'MEMORY_DB', tmp_path / 'legacy.sqlite3')
    monkeypatch.setattr(chat_archive, 'DB_PATH', tmp_path / 'archive.sqlite3')
    monkeypatch.setattr(memory_dashboard, 'STATE_PATH', tmp_path / 'control.json')
    monkeypatch.setattr(memory_embeddings, 'embedding_health', lambda **kw: None)
    monkeypatch.setattr(smart, '_TASKS', queue.Queue(maxsize=100))
    monkeypatch.setattr(smart, '_ENQUEUED', set())
    monkeypatch.setattr(smart, '_READER', None)
    monkeypatch.setattr(smart, '_CHAT_LOCK', threading.RLock())
    monkeypatch.setattr(smart, '_COMPLETE', None)
    pm.set_enabled(True)
    smart.set_enabled(True)


def chat(text, cid='fictional-a'):
    return {'id': cid, 'updated': 100, 'title': 'Synthetic project', 'messages': [{'role': 'user', 'content': text}]}


def output(text, *, value='natürliche Farben', subject='ich', field='vorliebe', episodes=None, kind='statement'):
    return json.dumps({'facts': [{'subject': subject, 'field': field, 'value': value, 'evidence': text,
        'confidence': .98, 'kind': kind}], 'episodes': episodes or []}, ensure_ascii=False)


def episode(text, **extra):
    return dict(title='Kindheit',theme='childhood',description=text,evidence=text,period='',people=[],status='statement',**extra)


def test_explicit_chat_persistence_cross_chat_recall_and_source():
    receipt = commands.execute(chat('Merk dir, dass ich bei Bildern natürliche Farben bevorzuge.')['messages'], chat_id='fictional-a')
    assert receipt['persisted'] is True
    assert len(pm.list_facts()) == 1
    recall = km.context('Welche Farben bevorzuge ich bei Bildern?')
    assert 'natürliche Farben' in recall and 'chat fictional-a' in recall
    # A fresh SQLite connection, not an in-memory receipt, contains the result.
    with sqlite3.connect(pm.DB_PATH) as conn:
        assert conn.execute("SELECT count(*) FROM facts WHERE status='active'").fetchone()[0] == 1
    assert commands.execute(chat('Merk dir, dass ich bei Bildern natürliche Farben bevorzuge.')['messages'], chat_id='fictional-a') == receipt


def test_remember_previous_statement_pins_correct_source_not_assistant():
    turns = [{'role':'system','content':'synthetic system'}, {'role':'user','content':'Ich bevorzuge natürliche Farben.'},
        {'role':'assistant','content':'Eine erfundene Antwort.'}, {'role':'user','content':'Merk dir das unbedingt.'}]
    result = commands.execute(turns, chat_id='fictional-a')
    assert result['persisted']
    stored = km.items()['items'][0]
    assert stored['value'] == 'Ich bevorzuge natürliche Farben.' and stored['pinned'] == 1
    assert stored['sources'][0]['ordinal'] == 0
    assert 'erfundene Antwort' not in json.dumps(stored)


def test_commands_never_claim_success_if_disabled_paused_or_missing_source():
    turns = chat('Merk dir: Ich nutze synthetische blaue Farben.')['messages']
    assert commands.execute(turns)['persisted'] is False
    memory_dashboard.set_paused(True)
    assert commands.execute(turns, chat_id='fictional-a')['action'] == 'paused'
    memory_dashboard.set_paused(False)
    pm.set_enabled(False)
    assert commands.execute(turns, chat_id='fictional-a')['action'] == 'disabled'


def test_large_story_chunking_checkpoint_resume_and_episodes(monkeypatch):
    text = 'Als Kind lebte ich in Musterstadt. ' * 160 + 'Mit zehn Jahren zog ich nach Beispielhausen.'
    source = chat(text)
    monkeypatch.setattr(smart, '_READER', lambda cid: source)
    calls = []
    def infer(payload):
        segment = json.loads(payload)['message']
        calls.append(segment)
        return json.dumps({'facts':[], 'episodes':[episode(segment.strip()[:900]), episode(segment.strip().split('. ')[-1])]})
    monkeypatch.setattr(smart, '_COMPLETE', infer)
    smart.process_message(source['id'], 0, smart._digest(text))
    assert len(calls) > 3 and all(len(c) <= 1500 for c in calls)
    assert ''.join(calls) == text
    assert km.items(kind='episode')['total'] >= 2
    assert km.stats()['jobs']['done'] == len(calls)
    assert 'Musterstadt' in km.context('Was weißt du über meine Kindheit?')
    smart.process_message(source['id'], 0, smart._digest(text))
    assert len(calls) == km.stats()['jobs']['done']


def test_failed_chunk_not_successful_and_explicit_resume_skips_completed(monkeypatch):
    text = 'Als Kind lebte ich in Musterstadt. ' * 100
    source = chat(text)
    monkeypatch.setattr(smart, '_READER', lambda cid: source)
    calls = []
    def fail_second(payload):
        calls.append(payload)
        if len(calls) == 2: raise RuntimeError('Private text must never enter diagnostics')
        return '{"facts":[],"episodes":[]}'
    monkeypatch.setattr(smart, '_COMPLETE', fail_second)
    smart.process_message(source['id'], 0, smart._digest(text))
    state = km.stats()
    assert state['jobs']['done'] == 1 and state['jobs']['error'] == 1
    assert 'Private text' not in json.dumps(state)
    with pm._connect() as conn:
        assert conn.execute('SELECT count(*) FROM smart_observed').fetchone()[0] == 0
        conn.execute("UPDATE analysis_jobs SET status='pending' WHERE status='error'")
    monkeypatch.setattr(smart, '_COMPLETE', lambda payload: '{"facts":[]}')
    smart.process_message(source['id'], 0, smart._digest(text))
    assert 'error' not in km.stats()['jobs']
    with pm._connect() as conn: assert conn.execute('SELECT count(*) FROM smart_observed').fetchone()[0] == 1


def test_invalid_model_json_is_error_not_processed(monkeypatch):
    source = chat('Ich bevorzuge natürliche Farben.')
    monkeypatch.setattr(smart, '_READER', lambda cid: source)
    monkeypatch.setattr(smart, '_COMPLETE', lambda payload: 'not JSON')
    smart.process_message(source['id'], 0, smart._digest(source['messages'][0]['content']))
    assert km.stats()['jobs']['error'] == 1
    assert pm.list_facts() == []


def test_related_experiences_across_chats_and_graph_provenance():
    a = 'Als Kind verbrachte ich die Ferien bei meiner Großmutter.'
    b = 'In meiner Kindheit zog meine Familie zweimal um.'
    for cid, text in [('fictional-a',a),('fictional-b',b)]:
        smart.apply(cid,0,text,json.dumps({'facts':[], 'episodes':[episode(text)]}))
    stored = km.items(kind='episode')['items']
    assert len(stored) == 2 and all(len(r['related']) == 1 for r in stored)
    assert all(r['sources'] for r in stored)
    assert km.items(kind='relation')['total'] == 2
    assert all(r['predicate'] == 'reported_experience' for r in km.items(kind='relation')['items'])


def test_episode_dates_names_and_psychological_interpretations_are_not_invented():
    text = 'Als Kind lebte ich in Musterstadt.'
    candidate = episode(text); candidate.update(period='1980', people=['Invented Person'])
    smart.apply('fictional-a',0,text,json.dumps({'facts':[], 'episodes':[candidate]}))
    row = km.items(kind='episode')['items'][0]
    assert row['period'] == '' and row['people'] == []
    bad = episode(text); bad['status'] = 'fact'
    assert smart.apply('fictional-b',0,text,json.dumps({'facts':[], 'episodes':[bad]}))['saved'] == 0
    assert km.items(kind='episode')['total'] == 1


def test_duplicate_facts_merge_sources_distinct_preferences_remain_separate():
    for cid in ('fictional-a','fictional-b'):
        text = 'Ich bevorzuge natürliche Farben.'
        smart.apply(cid,0,text,output(text))
    facts = km.items()['items']
    assert len(facts) == 1 and len(facts[0]['sources']) == 2
    text = 'Ich bevorzuge warme Beleuchtung.'
    smart.apply('fictional-c',0,text,output(text,value='warme Beleuchtung'))
    assert km.items()['total'] == 2
    assert pm.list_conflicts() == []


def test_correction_history_and_numeric_values_are_distinct():
    pm.observe('Mein Termin ist am 16. November', source_chat_id='fictional-a', source_ordinal=0)
    pm.observe('Mein Termin ist am 18. November', source_chat_id='fictional-b', source_ordinal=0)
    assert len(pm.list_conflicts()) == 1
    turns = [{'role':'user','content':'Mein Termin ist am 16. November'},
        {'role':'assistant','content':'Verstanden.'},
        {'role':'user','content':'Das stimmt nicht mehr. Stattdessen mein Termin ist am 19. November.'}]
    result = commands.execute(turns, chat_id='fictional-b')
    assert result['persisted'] and '19' in pm.list_facts()[0]['value']
    assert len(pm.list_facts(history=True)) == 2


def test_deleted_fact_cannot_return_as_paraphrase_episode_or_import():
    text = 'Ich bevorzuge natürliche Farben.'
    smart.apply('fictional-a',0,text,output(text))
    snapshot = km.export_data()
    pm.delete_fact(pm.list_facts()[0]['id'])
    smart.apply('fictional-a',0,text + ' Schon immer.',output(text))
    km.import_data(snapshot)
    assert pm.list_facts() == []
    assert km.context('Welche Farben bevorzuge ich?') == ''


def test_deleted_episode_is_blocked_after_rebuild():
    text = 'Als Kind lebte ich in Musterstadt.'
    smart.apply('fictional-a',0,text,json.dumps({'facts':[], 'episodes':[episode(text)]}))
    km.delete_episode(km.items(kind='episode')['items'][0]['id'])
    with pm._connect() as conn: conn.execute('DELETE FROM smart_observed')
    smart.apply('fictional-a',0,text,json.dumps({'facts':[], 'episodes':[episode(text)]}))
    assert km.items(kind='episode')['total'] == 0


def test_fictional_example_retracts_previous_statement_and_blocks_extraction():
    previous = 'Ich bevorzuge natürliche Farben.'
    pm.index_chat(chat(previous))
    result = commands.execute([{'role':'user','content':previous}, {'role':'user','content':'Das war nur ein Beispiel, merk dir das nicht.'}], chat_id='fictional-a')
    assert result['persisted'] and pm.list_facts() == []
    smart.apply('fictional-a',0,previous,output(previous))
    assert pm.list_facts() == []


def test_ambiguous_forget_requires_scope_and_active_forget_has_receipt():
    commands.execute(chat('Merk dir: Ich bevorzuge natürliche Farben.')['messages'], chat_id='fictional-a')
    assert commands.execute(chat('Vergiss natürliche Farben.')['messages'], chat_id='fictional-b')['action'] == 'clarify'
    assert pm.list_facts()
    result = commands.execute(chat('Vergiss nur die aktive Erinnerung über natürliche Farben.')['messages'], chat_id='fictional-b')
    assert result['persisted'] and result['removed'] == 1
    assert not pm.list_facts()


def test_unrelated_work_query_cannot_reveal_personal_episodes_or_relationship():
    text = 'Als Kind lebte ich in Musterstadt und lernte Python.'
    smart.apply('fictional-a',0,text,json.dumps({'facts':[], 'episodes':[episode(text)]}))
    pm.observe('Meine Partnerin heißt Mira',source_chat_id='fictional-b')
    assert km.context('Wie schreibe ich eine Funktion in Python?') == ''
    assert 'Musterstadt' in km.context('Meine Kindheit und Python')


def test_sandforge_decisions_recalled_with_sources_not_completed_actions():
    text = 'Für das Projekt Sandforge plane ich eine stärkere Spiel-KI.'
    smart.apply('fictional-a',0,text,output(text,value='stärkere Spiel-KI',subject='projekte.sandforge',field='ziel',kind='plan'))
    recall = km.context('Was haben wir für Sandforge geplant?')
    assert 'stärkere Spiel-KI' in recall and '(plan)' in recall
    assert 'chat fictional-a message 0' in recall and 'plans are not completed' in recall


def test_large_archive_tail_search_and_edit_revisions_are_lossless():
    chat_archive.set_enabled(True)
    source = chat('Synthetischer Text. ' * 16000 + 'EinzigartigerArchivschluss')
    chat_archive.index_chat(source)
    found = chat_archive.search('EinzigartigerArchivschluss')
    assert found and 'EinzigartigerArchivschluss' in found[0]['excerpt']
    source['messages'][0]['content'] = 'Neue synthetische Fassung.'
    chat_archive.index_chat(source)
    with chat_archive._connect() as conn:
        original = conn.execute('SELECT content FROM archive_revisions').fetchone()[0]
    assert original.endswith('EinzigartigerArchivschluss')


def test_real_metadata_preserves_failure_and_parameters():
    from agent import archive_activity_context
    chat_archive.set_enabled(True)
    source = chat('Generiere ein synthetisches Video.')
    source['messages'].append({'role':'assistant','content':'Fehlgeschlagen', 'video_job': {
        'status':'failed', 'model':'fictional-video-model', 'prompt':'Synthetic scene',
        'payload': {'seed':42,'steps':12,'width':640,'height':480,'scheduler':'example','fps':24}}})
    chat_archive.index_chat(source)
    rows = archive_activity_context.inventory(kind='video')['activities']
    assert rows[0]['status'] == 'failed'
    assert rows[0]['parameters']['seed'] == 42 and rows[0]['parameters']['steps'] == 12
    assert 'cfg_scale' not in rows[0]['parameters']
    assert 'status=failed' in archive_activity_context.context('Welche Videos habe ich erstellt?')


def test_import_roundtrip_transaction_and_deletion_rules(tmp_path,monkeypatch):
    text = 'Ich bevorzuge natürliche Farben.'
    smart.apply('fictional-a',0,text,output(text))
    snapshot = km.export_data()
    new_db = tmp_path/'restored.sqlite3'
    monkeypatch.setattr(pm,'DB_PATH',new_db)
    pm.set_enabled(True)
    assert km.import_data(snapshot)['persisted']
    assert km.items()['total'] == 1
    bad = json.loads(json.dumps(snapshot)); bad['tables']['facts'][0]['unexpected'] = 'value'
    with pytest.raises(ValueError): km.import_data(bad)
    assert km.items()['total'] == 1
    with pm._connect() as conn: assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_additive_migration_retains_legacy_facts(tmp_path,monkeypatch):
    path = tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE facts(id TEXT PRIMARY KEY,subject TEXT,field TEXT,value TEXT,sensitive INTEGER,source_chat_id TEXT,source_ordinal INTEGER,status TEXT,created_at REAL,updated_at REAL)')
        conn.execute("INSERT INTO facts VALUES('old','ich','beruf','Synthetischer Beruf',0,NULL,NULL,'active',1,1)")
    monkeypatch.setattr(pm,'DB_PATH',path)
    pm.set_enabled(True)
    assert pm.list_facts()[0]['id'] == 'old'
    assert km.items()['items'][0]['value'] == 'Synthetischer Beruf'
    assert path.stat().st_mode & 0o777 == 0o600


def test_api_edit_delete_history_and_schema_validation():
    from agent.personal_memory_routes import install_routes as personal_routes
    app = FastAPI(); install_routes(app); personal_routes(app, object())
    with TestClient(app) as client:
        result = client.post('/api/knowledge-memory/command',json={'chat_id':'fictional-a','messages':chat('Merk dir: Ich bevorzuge natürliche Farben.')['messages']}).json()
        fid = result['fact_ids'][0]
        edited = client.patch('/api/personal-memory/facts/'+fid,json={'value':'Ich bevorzuge warme Farben.'})
        assert edited.status_code == 200
        new_id = edited.json()['fact_id']
        assert len(client.get('/api/knowledge-memory/history/'+new_id).json()['items']) == 2
        assert client.delete('/api/personal-memory/facts/'+new_id).status_code == 200
        assert client.get('/api/knowledge-memory/items').json()['total'] == 0
        assert client.post('/api/knowledge-memory/import',json={'format':'wrong'}).status_code == 422


def test_scopes_prevent_extraction_but_retain_existing_data():
    km.set_scopes(['work'])
    text = 'Ich bevorzuge natürliche Farben.'
    smart.apply('fictional-a',0,text,output(text))
    assert pm.list_facts() == []
    assert km.scopes() == ['work']


def test_secret_and_example_never_scheduled(monkeypatch):
    source = chat('Mein API Key ist SYNTHETIC_PLACEHOLDER_ONLY und ich mag Farben.')
    monkeypatch.setattr(smart,'_READER',lambda cid: source)
    assert smart.enqueue(source) == 0
    pm.index_chat(source)
    assert pm.list_facts() == []
    assert commands.execute(chat('Merk dir: Mein Passwort ist synthetic-only.')['messages'],chat_id='fictional-a')['persisted'] is False


def test_pagination_reaches_older_records_beyond_2000():
    with pm._connect() as conn:
        pm._schema(conn)
        conn.executemany('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?)',[(str(i),'ich','notiz.'+str(i),'synthetic value '+str(i),0,None,None,'active',i,i) for i in range(2050)])
    result = km.items(query='synthetic value 0')
    assert result['total'] == 1
    assert pm.list_facts('synthetic value 0')[0]['id'] == '0'
    assert km.items(offset=2040,limit=30)['next_offset'] is None


def test_semantic_vector_batching_and_query_uses_existing_local_service(monkeypatch):
    text = 'Ich bevorzuge natürliche Farben.'
    smart.apply('fictional-a',0,text,output(text))
    monkeypatch.setattr(memory_embeddings,'embedding_health',lambda **kw: {'model':'synthetic-embedding','dimensions':2})
    calls=[]
    def request(path,payload,**kw):
        calls.append((path,payload))
        return {'model':'synthetic-embedding','dimensions':2,'vectors':[[1.,0.]] * (len(payload['texts']) if 'texts' in payload else 1)}
    monkeypatch.setattr(memory_embeddings,'_request',request)
    assert km.embed_pending() == 1
    assert km.embed_pending() == 0
    assert 'natürliche Farben' in km.context('Welche Ästhetik gefällt mir?',semantic=True)
    assert calls[0][0] == '/embeddings' and calls[-1][0] == '/embedding'


def test_remote_embedding_endpoint_rejected_before_network(monkeypatch):
    monkeypatch.setattr(memory_embeddings,'EMBEDDINGS_URL','https://example.invalid')
    with pytest.raises(ValueError,match='loopback'): memory_embeddings._request('/embedding',{'text':'synthetic only'})


def test_original_deletion_verifies_sources_and_stale_saves_cannot_restore():
    import copy
    from agent import memory_forgetting
    data = chat('Ich bevorzuge natürliche Farben.')
    data['messages'].append({'role':'assistant','content':'Du bevorzugst natürliche Farben.'})
    old = copy.deepcopy(data)
    pm.index_chat(data)
    class Host:
        CHATS_LOCK = threading.RLock()
        @staticmethod
        def read_chat(cid): return copy.deepcopy(data)
        @staticmethod
        def write_chat(updated):
            data.update(copy.deepcopy(updated))
    result = commands.execute(chat('Vergiss auch die ursprünglichen Chat-Nachrichten über natürliche Farben.')['messages'],chat_id='fictional-delete',chat_host=Host)
    assert result['persisted'] and result['removed_messages'] == 2
    assert data['messages'] == [] and pm.list_facts() == []
    assert memory_forgetting.filter_deleted_originals(old)['messages'] == []


def test_active_deletion_also_blocks_legacy_and_archived_replies():
    text = 'Ich bevorzuge natürliche Farben.'
    memory.observe_user_message(text,source_chat_id='fictional-a')
    pm.index_chat(chat(text))
    chat_archive.set_enabled(True)
    data=chat(text);data['messages'].append({'role':'assistant','content':'Du bevorzugst natürliche Farben.'})
    chat_archive.index_chat(data)
    assert memory.list_memories()
    pm.delete_fact(pm.list_facts()[0]['id'])
    assert memory.retrieve('natürliche Farben') == []
    assert chat_archive.search('natürliche Farben') == []
    memory.observe_user_message(text,source_chat_id='fictional-a')
    assert memory.retrieve('natürliche Farben') == []


def test_all_topics_inventory_includes_life_story_with_pagination():
    text='Als Kind lebte ich in Musterstadt.'
    smart.apply('fictional-a',0,text,json.dumps({'facts':[],'episodes':[episode(text)]}))
    pm.create_fact('ich','beruf','Synthetischer Entwickler')
    page=km.items(kind='all',limit=1)
    assert page['total']==2
    assert {r['object_type'] for r in page['items']}=={'fact','episode'}


def test_equivalent_preference_wording_reuses_sources_without_erasing_distinctions():
    pm.index_chat(chat('Ich bevorzuge bei meinen Bildern natürliche Farben.'))
    text='Bei Bildern bevorzuge ich natürliche Farben.'
    smart.apply('fictional-b',0,text,output(text))
    assert km.items()['total']==1
    assert len(km.items()['items'][0]['sources'])==2
    other='Ich bevorzuge warme Farben.'
    smart.apply('fictional-c',0,other,output(other,value='warme Farben'))
    assert km.items()['total']==2


def test_foreground_chat_defers_background_model_work(monkeypatch):
    from agent import run_state
    source=chat('Ich bevorzuge natürliche Farben.')
    monkeypatch.setattr(smart,'_READER',lambda cid:source)
    monkeypatch.setattr(smart,'_COMPLETE',lambda payload:pytest.fail('Foreground work must take priority'))
    monkeypatch.setattr(run_state,'chat_stream_progress_is_recent',lambda age:True)
    smart.process_message(source['id'],0,smart._digest(source['messages'][0]['content']))
    assert km.stats()['jobs']['pending']==1


def test_model_suggested_private_query_cannot_escalate_original_user_scope():
    text='Als Kind lebte ich in Musterstadt.'
    smart.apply('fictional-a',0,text,json.dumps({'facts':[],'episodes':[episode(text)]}))
    assert km.context('Was weißt du über meine Kindheit?',privacy_query='Erkläre einen Python-Algorithmus.')==''


def test_hypothetical_episode_is_never_promoted_to_autobiography():
    text='Wenn ich als Kind in Musterstadt gelebt hätte, wäre vieles anders.'
    smart.apply('fictional-a',0,text,json.dumps({'facts':[],'episodes':[episode(text)]}))
    assert km.items(kind='episode')['total']==0


def test_explicitly_remembered_hypothesis_is_labeled_assumption():
    receipt=commands.execute(chat('Merk dir: Wenn ich Architekt wäre, würde ich Häuser bauen.')['messages'],chat_id='fictional-a')
    assert receipt['persisted']
    assert km.items()['items'][0]['kind']=='assumption'


def test_grounded_autobiographic_fallback_when_local_model_omits_episodes():
    text='Als Kind lebte ich in Musterstadt. Mit zehn Jahren zog ich nach Beispielhausen.'
    smart.apply('fictional-a',0,text,'{"facts":[],"episodes":[]}')
    episodes=km.items(kind='episode')['items']
    assert len(episodes)==2
    assert all(e['description'] in text for e in episodes)
    assert 'fictional-a' in km.context('Was weißt du über meine Kindheit?')


def test_forgetting_survives_opt_out_and_reenable_in_independent_archive():
    text='Ich bevorzuge natürliche Farben.'
    data=chat(text);pm.index_chat(data)
    chat_archive.set_enabled(True);chat_archive.index_chat(data)
    pm.delete_fact(pm.list_facts()[0]['id'])
    pm.set_enabled(False)
    assert chat_archive.search('natürliche Farben')==[]
    pm.set_enabled(True);pm.rebuild([data])
    assert chat_archive.search('natürliche Farben')==[] and pm.list_facts()==[]


def test_derived_scope_erases_indexed_text_without_touching_source():
    text='Ich bevorzuge natürliche Farben.'
    data=chat(text);pm.index_chat(data)
    chat_archive.set_enabled(True);chat_archive.index_chat(data)
    result=commands.execute(chat('Vergiss die abgeleiteten Daten über natürliche Farben.')['messages'],chat_id='fictional-delete')
    assert result['persisted'] and data['messages'][0]['content']==text
    with chat_archive._connect() as conn: assert conn.execute('SELECT count(*) FROM archive_messages').fetchone()[0]==0
