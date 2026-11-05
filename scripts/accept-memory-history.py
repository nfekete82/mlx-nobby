#!/usr/bin/env python3
"""Private-history acceptance against the already selected local Qwen.

Requires a private snapshot outside Git (backup/, manifest.json). Creates its
own isolated home from that backup. No production Agent/Web request, model
switch, service restart, original-data write or private Git artifact is used.
The real runtime stream handler and MemoryChatMiddleware compose the answers;
only service lifecycle/model selection are replaced with a fixed, read-only
connection to the already configured model. Embeddings are disabled for this
SQLite/FTS acceptance, so no embedding service is started or contacted.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_root(path):
    path = path.resolve(strict=True)
    if any((p / '.git').exists() for p in [path, *path.parents]):
        raise ValueError('Private acceptance files must be outside Git')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--cases', type=Path, help='Private JSON with question, required and forbidden regex lists')
    parser.add_argument('--phase', choices=['extract', 'answers', 'verify'], required=True)
    parser.add_argument('--interrupt-after', type=int, default=0)
    parser.add_argument('--resume-jobs-only', action='store_true',help='Resume durable work/retries without resetting attempt counts or rescanning sources')
    parser.add_argument('--config', type=Path, default=Path.home()/'.config/mlx-server/config')
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    root = private_root(args.snapshot)
    raw_manifest = json.loads((root/'manifest.json').read_text())
    backup = root/'backup'
    if raw_manifest.get('format') == 1 and isinstance(raw_manifest.get('files'),list):
        backup = root/'data/mlx-web'
        manifest = {str(Path(item['path']).relative_to('data/mlx-web')):item['sha256']
                    for item in raw_manifest['files'] if item['path'].startswith('data/mlx-web/')}
    else:
        manifest = raw_manifest
    if not manifest: raise ValueError('No memory/chat files in snapshot')
    for rel, expected in manifest.items():
        path = (backup/rel).resolve()
        if backup not in path.parents or sha(path) != expected:
            raise RuntimeError('Backup checksum failed')
    config = {}
    for line in args.config.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k,v = line.split('=',1); config[k.strip()] = v.strip().strip('\"').strip("'")
    model = config['MODEL']; port = int(config.get('PORT',8000))
    if port in (8090,8010,8096) or 'qwen' not in model.casefold() or 'image' in model.casefold():
        raise ValueError('Refusing a production Agent/Web or non-Qwen model target')
    isolated_home = root/'isolated-home'
    data = isolated_home/'.config/mlx-web'
    if any(p.is_symlink() for p in (backup,isolated_home,isolated_home/'.config',data)):
        raise ValueError('Symlinked acceptance data root')
    if isolated_home.exists() and any(p.is_symlink() for p in isolated_home.rglob('*')):
        raise ValueError('Symlink in isolated acceptance home')
    if not data.exists():
        data.parent.mkdir(parents=True, mode=0o700)
        shutil.copytree(backup,data)
    cfg = isolated_home/'.config/mlx-server/config'
    cfg.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    cfg.write_text(f'MODEL="{model}"\nPORT="{port}"\nTHINKING="false"\n')
    cfg.chmod(0o600)
    # Every module-level and dynamic default, including runtime logs, is private.
    with patch.object(Path, 'home', return_value=isolated_home):
        from agent import app as host, personal_memory as pm, knowledge_memory as km
        from agent import semantic_personal_memory as smart, smart_full_history as full
        from agent import memory_embeddings as embeddings, chat_archive, memory_dashboard
        from agent.memory_middleware import MemoryChatMiddleware
        from fastapi.testclient import TestClient
        pm.set_enabled(True); smart.set_enabled(True); chat_archive.set_enabled(True)
        memory_dashboard.set_paused(False)
        embeddings.embedding_health = lambda **kwargs: None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        calls = 0
        def complete(payload):
            nonlocal calls
            if args.interrupt_after and calls >= args.interrupt_after:
                # Real process death between committed segments. No cleanup or
                # in-memory worker state can make the subsequent run succeed.
                os._exit(75)
            request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                data=json.dumps({'model':model,'messages':smart.extraction_messages(payload), 'max_tokens':3000, 'temperature':0,
                    'chat_template_kwargs':{'enable_thinking':False}}).encode(),
                headers={'Content-Type':'application/json'})
            started = time.monotonic()
            with opener.open(request,timeout=args.timeout) as response: result=json.load(response)
            choice = result['choices'][0]
            if choice.get('finish_reason') == 'length': raise ValueError('Truncated extraction')
            raw = choice['message'].get('content') or ''
            output = root/'extractions'; output.mkdir(exist_ok=True,mode=0o700)
            with (output/'calls.jsonl').open('a') as log:
                log.write(json.dumps({'payload_digest':km.digest(payload),'extractor_version':km.VERSION,'seconds':round(time.monotonic()-started,3),
                                      'model':model,'finish_reason':choice.get('finish_reason')})+'\n')
            (output/(km.digest(payload)+'.json')).write_text(json.dumps({'payload':json.loads(payload),'result':result},ensure_ascii=False,indent=2))
            calls += 1
            print('EXTRACTED_SEGMENT',calls,flush=True)
            return raw
        smart._READER = host.memory_chat_reader
        smart._REVISION_READER = host.memory_chat_reader
        smart._CHAT_LOCK = host.CHATS_LOCK
        smart._COMPLETE = complete
        smart._WORKER_STOP.clear()
        fingerprints_path=root/'source-fingerprints.json'
        fingerprints=json.loads(fingerprints_path.read_text()) if fingerprints_path.exists() else {}
        for source_root in (data/'chats',data/'long-term-chat-memory'):
            for source in source_root.rglob('*.json'):
                rel=str(source.relative_to(data)); actual=sha(source)
                if rel in fingerprints and fingerprints[rel]!=actual:
                    raise RuntimeError('Copied original source changed')
                fingerprints[rel]=actual
        fingerprints_path.write_text(json.dumps(fingerprints,indent=2))
        if args.phase == 'extract':
            if not args.resume_jobs_only:
                full.start(host.iter_memory_chats)
                full._THREAD.join(timeout=120)
                if full._THREAD.is_alive(): raise RuntimeError('Source discovery did not finish')
            waiting = time.monotonic()
            while True:
                row = km.next_job()
                if not row:
                    if km.stats().get('retryable_errors') and time.monotonic()-waiting<args.timeout:
                        time.sleep(.5)
                        continue
                    break
                smart.process_message(*row)
                waiting = time.monotonic()
            state=smart.status()
            (root/'extraction-summary.json').write_text(json.dumps(state,indent=2))
            print('EXTRACTION_STATUS',json.dumps(state['full_scan']),flush=True)
            return 0 if state['full_scan']['complete'] else 1
        if args.phase == 'answers':
            import re
            if args.cases is None: parser.error('--answers requires --cases')
            cases=json.loads(args.cases.read_text())
            if len(cases)<10: raise ValueError('At least ten independent private acceptance cases are required')
            # Disable all lifecycle effects; keep the actual inference transport,
            # middleware, runtime stream worker, SSE parser and upstream Qwen.
            host.runtime_coordinator.chat_runtime = lambda *a,**k: contextlib.nullcontext()
            host.ensure_model_for_role = lambda role: {'resolved':{'repo':model,'backend':'mlx'}}
            host.load_config = lambda: {'PORT':port,'THINKING':'false'}
            host.app.add_middleware(MemoryChatMiddleware,chat_host=host)
            results=[]
            source_ids={chat['id'] for chat in host.iter_memory_chats()}
            with TestClient(host.app,base_url='http://localhost') as client:
                for index, case in enumerate(cases):
                    started=time.monotonic()
                    response=client.post('/api/runtime/chat/stream',json={'messages':[
                        {'role':'system','content':'Antworte auf Deutsch. Nutze ausschließlich belegte Erinnerungen. Zitiere die Chat- und Nachrichtenquellen. Sage klar, wenn Angaben fehlen oder widersprüchlich sind. Erfinde nichts. Fasse intime Themen nur sachlich und nicht grafisch zusammen.'},
                        {'role':'user','content':case['question']}], 'temperature':0,'max_tokens':1800})
                    response.raise_for_status()
                    answer=''
                    if 'event: error' in response.text: raise RuntimeError('Runtime stream failed')
                    for line in response.text.splitlines():
                        if line.startswith('data: '):
                            item=json.loads(line[6:])
                            if item.get('type')=='content': answer+=item.get('text','')
                    checks=([bool(re.search(p,answer,re.I)) for p in case.get('required',[])]
                            +[not re.search(p,answer,re.I) for p in case.get('forbidden',[])])
                    cited_ids=set(re.findall(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',answer,re.I))
                    sourced=bool(cited_ids & source_ids) and not (cited_ids - source_ids)
                    if case.get('expects_absence') and not cited_ids: sourced=True
                    passed=bool(answer and checks and all(checks) and sourced)
                    results.append({'case':case,'answer':answer,'passed':passed,'sourced':sourced,'seconds':round(time.monotonic()-started,2)})
                    (root/'answers.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
                    print('ANSWER',index+1,'PASS' if passed else 'FAIL',flush=True)
            return 0 if all(r['passed'] for r in results) else 1
        # Existing records and conflicts must remain byte-equivalent as rows.
        original=sqlite3.connect((backup/'personal-memory.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
        current=sqlite3.connect(pm.DB_PATH)
        for table in ('facts','conflicts','forgotten','excluded'):
            columns=[r[1] for r in original.execute(f'PRAGMA table_info({table})')]
            before=list(original.execute(f'SELECT * FROM {table}'))
            after=set(current.execute('SELECT '+','.join(columns)+' FROM '+table))
            if any(row not in after for row in before):
                raise RuntimeError('Existing record changed or disappeared: '+table)
        for rel, expected in manifest.items():
            if sha(backup/rel)!=expected: raise RuntimeError('Backup changed')
            if rel.startswith(('chats/','long-term-chat-memory/')) and sha(data/rel)!=expected:
                raise RuntimeError('Copied source changed')
        for rel, expected in fingerprints.items():
            if sha(data/rel)!=expected: raise RuntimeError('Recovered copied source changed')
        integrity=current.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok' or current.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Database integrity failed')
        before_count=original.execute('SELECT count(*) FROM facts').fetchone()[0]
        total=current.execute('SELECT count(*) FROM facts').fetchone()[0]
        projects=current.execute("SELECT count(*) FROM facts WHERE subject LIKE 'projekte.%'").fetchone()[0]
        report={'preserved_original_rows':True,'backup_hashes_unchanged':True,'copied_sources_unchanged':True,
                'sqlite_integrity':integrity,'new_facts':total-before_count,'project_facts':projects,
                'source_files_verified':len(fingerprints),
                'status':smart.status()}
        (root/'verification.json').write_text(json.dumps(report,indent=2))
        print('VERIFICATION',json.dumps({k:v for k,v in report.items() if k!='status'}),flush=True)
        original.close();current.close()
        return 0


if __name__=='__main__':
    # Private artifacts inherit owner-only permissions, including crash logs.
    os.umask(0o077)
    raise SystemExit(main())
