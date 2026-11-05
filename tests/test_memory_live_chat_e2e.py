"""Ordinary chat saves -> real stores -> middleware generation boundary.

CPU regression with fictional data; no model/service or original-data access.
The local acceptance companion exercises the same boundary with real Qwen SSE.
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent import app as host, chat_archive, memory, memory_dashboard, memory_embeddings
from agent import personal_memory as pm, semantic_personal_memory as smart
from agent.memory_middleware import MemoryChatMiddleware


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path/'private'
    monkeypatch.setattr(host,'CHAT_DIRECTORY',root/'chats')
    monkeypatch.setattr(pm,'DB_PATH',root/'personal.sqlite3')
    monkeypatch.setattr(memory,'MEMORY_DB',root/'legacy.sqlite3')
    monkeypatch.setattr(chat_archive,'DB_PATH',root/'archive.sqlite3')
    monkeypatch.setattr(memory_dashboard,'STATE_PATH',root/'control.json')
    monkeypatch.setattr(memory_embeddings,'embedding_health',lambda **kw:None)
    monkeypatch.setattr(smart,'_READER',None)
    pm.set_enabled(True)
    app = FastAPI()
    app.add_api_route('/api/chats/{chat_id}',host.put_chat,methods=['PUT'])
    app.add_middleware(MemoryChatMiddleware,chat_host=host)

    @app.post('/api/runtime/chat/stream')
    async def generation_boundary(request:Request):
        return await request.json()

    with TestClient(app,base_url='http://localhost') as api:
        yield api
    middleware=app.middleware_stack
    while not isinstance(middleware,MemoryChatMiddleware): middleware=middleware.app
    for pool in (middleware._memory_executor,middleware._private_executor,middleware._overview_executor):
        pool.shutdown(wait=True,cancel_futures=True)
        assert not any(thread.is_alive() for thread in pool._threads)


@pytest.mark.parametrize('save_conflict_first',[False,True],ids=['generation-before-autosave','autosave-before-generation'])
def test_ordinary_chat_persists_deduplicates_and_requests_conflict_clarification(client,save_conflict_first):
    cid='ordinary-memory-flow'
    first={'role':'user','content':'Meine Freundin heißt Mira.'}
    history=[first]
    def save(updated):
        response=client.put('/api/chats/'+cid,json={
            'id':cid,'title':'Ordinary chat','created':1,'updated':updated,
            'messages':history,'revision':0,
        })
        assert response.status_code==200
    def generate():
        response=client.post('/api/runtime/chat/stream',json={'chat_id':cid,'messages':history})
        assert response.status_code==200
        assert 'memory_receipt' not in response.text
        return '\n'.join(m['content'] for m in response.json()['messages'] if m['role']=='system')

    save(100)
    original=pm.list_facts()
    assert len(original)==1 and original[0]['value']=='Mira'
    assert original[0]['source_chat_id']==cid
    assert 'Mira' in generate()

    history.extend([{'role':'assistant','content':'Verstanden.'},dict(first)])
    save(101)
    assert pm.list_facts(history=True)==original
    assert pm.list_conflicts()==[]

    history.extend([{'role':'assistant','content':'Verstanden.'},
                    {'role':'user','content':'Meine Freundin heißt Nora.'}])
    if save_conflict_first: save(102)
    context=generate()
    assert 'MEMORY CLARIFICATION REQUIRED' in context
    assert 'Mira' in context and 'Nora' in context and 'Ask which' in context
    if not save_conflict_first: save(102)
    assert pm.list_facts(history=True)==original
    pending=pm.list_conflicts()
    assert len(pending)==1 and pending[0]['proposed_value']=='Nora'
    save(103)
    assert pm.list_conflicts()==pending
    assert pm.list_facts(history=True)==original
