"""Real Chromium + actual memory routes, only synthetic temporary SQLite data."""
import socket
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from agent import knowledge_memory as km, personal_memory as pm, memory_dashboard
from agent import memory, chat_archive, semantic_personal_memory as smart
from agent.knowledge_memory_routes import install_routes as knowledge_routes
from agent.memory_dashboard_routes import install_routes as dashboard_routes
from agent.personal_memory_routes import install_routes as personal_routes
from agent.smart_memory_routes import install_routes as smart_routes
from backend.memory_manager_routes import install_routes as web_routes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def knowledge_web(tmp_path,monkeypatch):
    monkeypatch.setattr(pm,'DB_PATH',tmp_path/'personal.sqlite3')
    monkeypatch.setattr(memory,'MEMORY_DB',tmp_path/'legacy.sqlite3')
    monkeypatch.setattr(chat_archive,'DB_PATH',tmp_path/'archive.sqlite3')
    monkeypatch.setattr(memory_dashboard,'STATE_PATH',tmp_path/'pause.json')
    pm.set_enabled(True)
    pm.observe('Ich bevorzuge natürliche Farben.',source_chat_id='synthetic-source',source_ordinal=0)
    pm.observe('Ich liebe warme Beleuchtung.',source_chat_id='synthetic-source',source_ordinal=2)
    api = FastAPI()
    host = type('Host',(),{'CHATS_LOCK':threading.RLock(),'list_chats':staticmethod(lambda:[])})
    knowledge_routes(api); dashboard_routes(api); personal_routes(api,host); smart_routes(api,host)
    transport = TestClient(api)
    app = FastAPI()
    def forward(method,path,**kw):
        response=transport.request(method,path,json=kw.get('payload'))
        if response.status_code>=400:
            from fastapi import HTTPException
            raise HTTPException(response.status_code,response.json().get('detail','Request failed'))
        return response.json()
    web_routes(app,forward)
    app.mount('/assets',StaticFiles(directory=ROOT/'frontend/assets'),name='assets')
    app.mount('/i18n',StaticFiles(directory=ROOT/'frontend/i18n'),name='i18n')
    @app.get('/')
    def page(lang: str='de'):
        selected = 'de' if lang=='de' else 'en'
        return HTMLResponse('<!doctype html><html><meta charset="utf-8"><title>Memory acceptance</title>'
            '<script>window.MLXI18n={getLanguage:()=>"'+selected+'"};</script>'
            '<main id="memoryManagerPane"><section class="settings-card">Advanced</section></main>'
            '<button id="memoryManagerTab">Memory</button><script src="/assets/chat/memory-overview.js"></script></html>')
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen()
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try: yield 'http://127.0.0.1:'+str(sock.getsockname()[1])
    finally:
        server.should_exit=True;thread.join(5);sock.close();transport.close()


@pytest.mark.parametrize('lang,label',[('de','Wissen & Lebensgeschichte'),('en','Knowledge & life story')])
def test_knowledge_browser_edit_pin_history_delete(browser,knowledge_web,lang,label):
    page=browser.new_page(viewport={'width':1100,'height':900})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(knowledge_web+'/?lang='+lang)
        page.locator('#memoryManagerTab').click()
        page.locator('#memoryKnowledge h3').filter(has_text=label).wait_for()
        card=page.locator('#memoryKnowledgeList article').filter(has_text='natürliche Farben')
        card.wait_for()
        source=card.locator('a').first
        assert 'memory_chat=synthetic-source' in source.get_attribute('href')
        pin='Als wichtig markieren' if lang=='de' else 'Mark important'
        card.get_by_role('button',name=pin,exact=True).click()
        card.get_by_role('button',name='Priorität aufheben' if lang=='de' else 'Remove priority',exact=True).wait_for()
        page.once('dialog',lambda dialog:dialog.accept('Ich bevorzuge weiches Licht.'))
        card.get_by_role('button',name='Bearbeiten' if lang=='de' else 'Edit',exact=True).click()
        updated=page.locator('#memoryKnowledgeList article').filter(has_text='weiches Licht')
        updated.wait_for()
        updated.locator('details summary').click()
        updated.locator('details').filter(has_text='natürliche Farben').wait_for()
        page.once('dialog',lambda dialog:dialog.accept())
        updated.get_by_role('button',name='Löschen' if lang=='de' else 'Delete',exact=True).click()
        page.wait_for_function("!document.querySelector('#memoryKnowledgeList').textContent.includes('weiches Licht')")
        assert not errors
    finally:page.close()


def test_knowledge_browser_merge_pagination_export_and_pause(browser,knowledge_web):
    page=browser.new_page()
    try:
        page.goto(knowledge_web)
        page.locator('#memoryManagerTab').click()
        checks=page.locator('#memoryKnowledgeList input[type=checkbox]')
        checks.first.wait_for(); assert checks.count()==2
        checks.nth(0).check();checks.nth(1).check()
        page.once('dialog',lambda dialog:dialog.accept('Ich bevorzuge natürliche Farben und warme Beleuchtung.'))
        page.locator('#memoryKnowledgeMerge').click()
        page.wait_for_function("document.querySelectorAll('#memoryKnowledgeList article').length===1")
        with page.expect_download() as download:
            page.get_by_role('button',name='Wissen exportieren').click()
        assert download.value.suggested_filename=='mlx-nobby-private-knowledge.json'
        page.locator('#memoryOverviewToggle').click()
        page.locator('#memoryOverviewMode').filter(has_text='pausiert').wait_for()
        assert km.items()['total']==1
    finally:page.close()


def test_knowledge_scopes_and_similarity_review_are_controlled(browser,knowledge_web):
    page=browser.new_page()
    try:
        page.goto(knowledge_web)
        page.locator('#memoryManagerTab').click()
        page.get_by_text('Welche Bereiche darf Nobby speichern?',exact=True).click()
        scopes=page.locator('#memoryKnowledgeScopes input[type=checkbox]')
        scopes.first.wait_for();assert scopes.count()==8
        page.locator('#memoryKnowledgeScopes input[value=life]').uncheck()
        page.wait_for_function("document.querySelector('#memoryOverviewNotice').textContent.includes('Lokal gespeichert')")
        assert 'life' not in km.scopes()
        page.get_by_text('Ähnliche Erinnerungen prüfen',exact=True).click()
        page.locator('#memoryKnowledgeSimilar p').wait_for()
        assert pm.list_facts()  # Scope changes preserve existing memories.
    finally:page.close()
