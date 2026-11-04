#!/usr/bin/env python3
"""Synthetic Chromium/API acceptance for the isolated real Agent on 8098 only.

No production data, external origins or inference services are used. All fixture
values below are invented. The dedicated preview must start with a fresh, opted-out Agent container.
"""
import json
import subprocess
import time
import uuid
from collections import deque

from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:8098'
PREFIX = 'synthetic-pr417-' + uuid.uuid4().hex[:12]
AGENT = 'mlx-pr417-preview-preview-agent-1'


def probe(message, chat_id=None):
    # Inspect the real enrichment function against the preview's own SQLite
    # stores. This is not an inference mock and creates no production endpoint.
    code = '''import json,sys
from agent import memory_lifecycle
body=json.loads(sys.argv[1])
result=memory_lifecycle.enrich_messages([{'role':'user','content':body['message']}],
    observe=False,source_chat_id=body.get('chat_id'))
print(json.dumps(result))
'''
    output = subprocess.check_output(['docker', 'exec', AGENT, 'python', '-c', code,
        json.dumps({'message': message, 'chat_id': chat_id})], text=True)
    return json.loads(output)


def run():
    info = json.loads(subprocess.check_output(['docker', 'inspect', AGENT], text=True))[0]
    assert not info['Mounts'] and not info['HostConfig']['PortBindings']
    assert info['Config']['Image'].startswith('mlx-pr417-agent:')
    assert 'HOME=/tmp/pr417-home' in info['Config']['Env']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route('**/*', lambda route: route.continue_()
                      if route.request.url.startswith(BASE + '/') else route.abort())
        request = context.request

        def api(method, path, payload=None):
            response = request.fetch(BASE + '/api/mlx/' + path, method=method,
                                     data=payload if payload is not None else None)
            assert response.ok, f'{method} {path}: {response.status}'
            return response.json()

        def facts(history=False):
            return api('GET', 'memory/personal/facts?history=' + str(history).lower())['facts']

        def save(suffix, text, updated):
            chat_id = PREFIX + '-' + suffix
            api('PUT', 'chats/' + chat_id, {'id': chat_id, 'title': 'Synthetic acceptance',
                'created': 1, 'updated': updated, 'messages': [{'role': 'user', 'content': text}],
                'expected_updated': -1})
            return chat_id

        deadline = time.monotonic() + 30
        while True:
            try:
                ready = request.get(BASE + '/api/mlx/memory/personal/status', timeout=1500).ok
            except Exception:
                ready = False
            if ready:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Isolated preview did not become ready within 30 seconds')
            time.sleep(0.2)
        assert api('GET', 'memory/personal/status')['enabled'] is False
        assert api('GET', 'memory/archive/status')['enabled'] is False
        source_id = save('name', 'Meine Freundin heißt Beispielperson', 100)
        old_id = save('old-date', 'Mein Termin ist am 16. November', 110)
        question_id = save('new-date', 'Mein Termin ist am 18. November', 120)
        archive_id = save('archive', 'syntheticarchivemarker plan alpha', 130)
        assert not facts()
        print('PASS 1: stores remain opted out until explicit opt-in')

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        # A static host keeps the real feature controllers and DOM while
        # preventing unrelated model/status/CDN calls during these focused tests.
        page.goto(BASE + '/api/health')
        page.evaluate('''() => { document.body.innerHTML =
            '<button id="memoryManagerTab">Memory</button><div id="memoryManagerPane"></div>'; }''')
        page.add_script_tag(url=BASE + '/assets/chat/memory-archive.js')
        page.add_script_tag(url=BASE + '/assets/chat/personal-memory.js')
        page.locator('#memoryManagerTab').click()
        expect(page.locator('#privateMemoryEnabled')).to_be_enabled()
        page.locator('#privateMemoryEnabled').check()
        expect(page.locator('#privateMemoryAdd')).to_be_enabled()
        page.locator('#localArchiveEnabled').check()
        expect(page.locator('#localArchiveRebuild')).to_be_enabled()
        assert api('GET', 'memory/personal/status')['enabled']
        assert api('GET', 'memory/archive/status')['enabled']
        name = page.locator('#privateMemoryFacts .memory-manager-card').filter(has_text='Beispielperson')
        expect(name).to_contain_text(source_id)
        expect(name).to_contain_text('#0')
        expect(page.locator('#privateMemoryConflicts')).to_contain_text('16. November')
        expect(page.locator('#privateMemoryConflicts')).to_contain_text('18. November')
        print('PASS 2: actual UI opt-in backfills source-linked facts and ordered conflicts')

        enriched = probe('Mein Termin ist am 18. November', question_id)
        assert any('CLARIFICATION REQUIRED' in m.get('content', '') for m in enriched)
        probe('Ja, das neue Datum stimmt', PREFIX + '-unrelated')
        assert len(api('GET', 'memory/personal/conflicts')['conflicts']) == 1
        rejected = """import json,sys,urllib.request,urllib.error
body=json.loads(sys.argv[1])
req=urllib.request.Request('http://127.0.0.1:8010/api/runtime/chat/stream',
 data=json.dumps(body).encode(),headers={'Origin':'https://foreign.invalid','Content-Type':'text/plain'})
try:
 response=urllib.request.urlopen(req,timeout=5)
 print(response.status)
except urllib.error.HTTPError as error:
 print(error.code)
"""
        status = subprocess.check_output(['docker', 'exec', AGENT, 'python', '-c', rejected,
            json.dumps({'chat_id': question_id, 'messages': [
                {'role': 'user', 'content': 'Ja, das neue Datum stimmt'}]})], text=True).strip()
        assert status == '403'
        assert len(api('GET', 'memory/personal/conflicts')['conflicts']) == 1
        probe('Ja, das neue Datum stimmt', question_id)
        assert not api('GET', 'memory/personal/conflicts')['conflicts']
        assert any('18. November' == f['value'] for f in facts())
        print('PASS 3: real enrichment asks for clarification; only the originating chat confirms it')

        page.locator('#privateMemoryReload').click()
        expect(page.locator('#privateMemoryConflicts')).not_to_contain_text('16. November')
        answers = deque(['partner', 'rufname', 'SYNTHETIC_EDITED_VALUE'])
        def edit_dialog(dialog):
            dialog.accept(answers.popleft())
        page.on('dialog', edit_dialog)
        name.get_by_role('button', name='Edit', exact=True).click()
        expect(page.locator('#privateMemoryFacts')).to_contain_text('SYNTHETIC_EDITED_VALUE')
        page.remove_listener('dialog', edit_dialog)
        edited = page.locator('#privateMemoryFacts .memory-manager-card').filter(has_text='SYNTHETIC_EDITED_VALUE')
        expect(edited).to_contain_text(source_id)
        page.locator('#privateMemoryHistory').check()
        expect(page.locator('#privateMemoryFacts')).to_contain_text('Beispielperson')
        page.once('dialog', lambda dialog: dialog.accept())
        edited.get_by_role('button', name='Delete', exact=True).click()
        expect(page.locator('#privateMemoryFacts')).not_to_contain_text('SYNTHETIC_EDITED_VALUE')
        expect(page.locator('#privateMemoryFacts')).not_to_contain_text('Beispielperson')
        api('POST', 'memory/personal/rebuild', {})
        assert not any(f['subject'] == 'partner' for f in facts(True))
        print('PASS 4: editing retains provenance; deletion removes renamed history and blocks rebuild resurrection')

        page.locator('#localArchiveQuery').fill('syntheticarchivemarker')
        page.locator('#localArchiveSearch').click()
        expect(page.locator('#localArchiveResults')).to_contain_text(archive_id)
        page.locator('#localArchiveResults button').click()
        expect(page.locator('#localArchiveResults')).not_to_contain_text(archive_id)
        api('POST', 'memory/archive/rebuild', {})
        assert not api('GET', 'memory/archive/search?query=syntheticarchivemarker')['results']
        assert api('GET', 'chats/' + archive_id)['chat']['messages']
        api('POST', 'memory/archive/include/' + archive_id, {})
        assert api('GET', 'memory/archive/search?query=syntheticarchivemarker')['results']
        api('DELETE', 'chats/' + archive_id)
        assert not api('GET', 'memory/archive/search?query=syntheticarchivemarker')['results']
        print('PASS 5: archive search/exclusion/rebuild/inclusion/deletion preserve the correct source lifecycle')

        page.locator('#privateMemoryEnabled').uncheck()
        expect(page.locator('#privateMemoryAdd')).to_be_disabled()
        page.locator('#localArchiveEnabled').uncheck()
        expect(page.locator('#localArchiveRebuild')).to_be_disabled()
        assert api('GET', 'memory/personal/status')['active_facts'] == 0
        assert api('GET', 'memory/archive/status')['indexed_messages'] == 0
        assert api('GET', 'chats/' + source_id)['chat']['messages']
        assert api('GET', 'chats/' + old_id)['chat']['messages']
        check = '''from pathlib import Path
import json,sqlite3
root=Path.home()/'.config/mlx-web'
result=[]
for path in root.glob('*'):
 if path.name in ('personal-memory.sqlite3','chat-archive.sqlite3'):
  conn=sqlite3.connect(path)
  ok=conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  conn.close()
  result.append({'private':path.stat().st_mode & 0o777 == 0o600,'integrity':ok})
print(json.dumps(result))
'''
        checks = json.loads(subprocess.check_output(['docker', 'exec', AGENT, 'python', '-c', check], text=True))
        assert checks and all(c['private'] and c['integrity'] for c in checks)
        assert not errors, errors
        print('PASS 6: opt-out purges derived stores, retains chats, and SQLite integrity/0600 checks pass')
        print(json.dumps({'origin': BASE, 'fixture_prefix': PREFIX, 'checks': 6, 'browser_errors': 0}))
        browser.close()


if __name__ == '__main__':
    run()
