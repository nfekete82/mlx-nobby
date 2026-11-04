#!/usr/bin/env python3
"""Synthetic end-to-end acceptance using the already active local model.

Uses the Agent's existing inference bridge/runtime lock, never switches models,
never writes production chats/settings/memory, never renders images/videos.
Every database and source chat is temporary. Prints no private configuration.
"""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import personal_memory as pm, knowledge_memory as km
from agent import memory_dashboard, memory, chat_archive
from agent import semantic_personal_memory as smart
from agent import memory_commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-url', default='http://127.0.0.1:8010')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.agent_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('Only a local loopback Agent is supported')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # Select only the model which is already loaded; no role resolver or switch API.
    with opener.open(args.agent_url + '/api/bridge/mlx/v1/models', timeout=10) as response:
        models = json.load(response).get('data', [])
    if not models: raise RuntimeError('No active local model')
    # /v1/models is a registry, not an active-model indicator; its first item
    # may be an image checkpoint. Read only the already selected text model.
    config = Path.home()/'.config/mlx-server/config'
    selected = None
    if config.exists():
        for line in config.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('MODEL='):
                selected=line.strip().split('=',1)[1].strip().strip('\"').strip("'")
    if not selected: raise RuntimeError('Cannot verify the already selected text model; refusing to switch or guess')
    model = selected
    if any(word in model.casefold() for word in ('qwen-image','flux','ltx','sdxl')):
        raise RuntimeError('The selected model is a media checkpoint, not a text extractor')
    print('SELECTED_TEXT_MODEL', '/'.join(model.rstrip('/').split('/')[-2:]),flush=True)
    def infer(messages):
        payload = {'model':model, 'messages':messages, 'temperature':0, 'max_tokens':1400,
                   'chat_template_kwargs':{'enable_thinking':False}}
        request = urllib.request.Request(args.agent_url + '/api/bridge/mlx/v1/chat/completions',
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        with opener.open(request, timeout=args.timeout) as response: result = json.load(response)
        choice = result['choices'][0]
        if choice.get('finish_reason') == 'length': raise RuntimeError('Truncated extraction output')
        raw = choice['message'].get('content') or ''
        try:
            parsed = json.loads(raw.strip().removeprefix('```json').removesuffix('```'))
            if not isinstance(parsed,dict) or not isinstance(parsed.get('facts'),list): raise ValueError()
        except (ValueError,TypeError):
            print('SYNTHETIC_MODEL_SCHEMA_FAILURE',json.dumps(raw[:3000],ensure_ascii=False),flush=True)
        return raw
    with tempfile.TemporaryDirectory(prefix='mlx-knowledge-acceptance-') as temp:
        root = Path(temp)
        pm.DB_PATH = root/'personal.sqlite3'; memory.MEMORY_DB = root/'legacy.sqlite3'
        chat_archive.DB_PATH = root/'archive.sqlite3'; memory_dashboard.STATE_PATH = root/'control.json'
        pm.set_enabled(True); smart.set_enabled(True)
        chats = {
            'synthetic-preference': {'id':'synthetic-preference','updated':1,'messages':[
                {'role':'user','content':'Ich bevorzuge bei meinen Bildern natürliche Farben.'}]},
            'synthetic-childhood': {'id':'synthetic-childhood','updated':2,'messages':[
                {'role':'user','content':'Als Kind lebte ich mit meiner Familie in Musterstadt. Mit zehn Jahren zog ich nach Beispielhausen. Dort lernte ich im Schachverein meine Freundin Mira kennen.'}]},
            'synthetic-project': {'id':'synthetic-project','updated':3,'messages':[
                {'role':'user','content':'Für mein Projekt Sandforge plane ich eine stärkere Spiel-KI mit WebGL.'}]},
        }
        smart._READER = chats.get; smart._CHAT_LOCK = threading.RLock()
        smart._COMPLETE = lambda message: infer([{'role':'system','content':smart._SYSTEM},{'role':'user','content':message}])
        started = time.monotonic()
        for cid, source in chats.items():
            text = source['messages'][0]['content']
            smart.process_message(cid,0,smart._digest(text))
            state = km.stats()
            if state['jobs'].get('error'): raise RuntimeError('Local extraction failed: ' + json.dumps(state['failed_sources']))
            print('PROCESSED',cid,flush=True)
        checks = {
            'grounded preference persisted': any('natürliche Farben' in f['value'] for f in pm.list_facts()),
            'childhood episodes persisted': any(s['chat_id']=='synthetic-childhood' for row in km.items(kind='episode')['items'] for s in row['sources']),
            'new-chat preference recall': 'natürliche Farben' in km.context('Welche Farben bevorzuge ich bei Bildern?'),
            'new-chat childhood sources': 'synthetic-childhood' in km.context('Was weißt du über meine Kindheit?'),
            'project recall': 'Sandforge' in km.context('Was weißt du über Sandforge?') or 'sandforge' in km.context('Was weißt du über Sandforge?'),
            'unrelated query privacy': 'Musterstadt' not in km.context('Wie schreibe ich einen Python-Sortieralgorithmus?'),
        }
        receipt = memory_commands.execute([{'role':'user','content':'Ich bevorzuge warme Beleuchtung.'},
            {'role':'assistant','content':'Verstanden.'},{'role':'user','content':'Merk dir das unbedingt.'}], chat_id='synthetic-command')
        checks['explicit command persistence'] = receipt['persisted'] and any('warme Beleuchtung' in f['value'] for f in pm.list_facts())
        stored = next((f for f in pm.list_facts() if 'natürliche Farben' in f['value']),None)
        if stored:
            backup = km.export_data(); pm.delete_fact(stored['id']); km.import_data(backup)
            checks['deletion survives reimport'] = not any('natürliche Farben' in f['value'] for f in pm.list_facts())
        if not all(checks.values()):
            print('SYNTHETIC_EPISODE_DIAGNOSTICS',json.dumps(km.items(kind='episode'),ensure_ascii=False),flush=True)
        for label, passed in checks.items(): print(('PASS' if passed else 'FAIL') + ' | ' + label, flush=True)
        print('RESULT',sum(checks.values()),'/',len(checks),'elapsed_seconds',round(time.monotonic()-started,2),flush=True)
        return 0 if all(checks.values()) else 1

if __name__ == '__main__': raise SystemExit(main())
