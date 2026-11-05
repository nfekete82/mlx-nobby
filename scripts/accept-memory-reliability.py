#!/usr/bin/env python3
"""Fourteen fictional messages through the real local memory pipeline.

No production configuration, databases, archive, embeddings or foreground LLM.
--live uses only the already running 4B endpoint; --replay reuses its recorded
responses to isolate persistence/retrieval changes from model variability.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import personal_memory as pm, knowledge_memory as km
from agent import semantic_personal_memory as smart, dedicated_memory_model as mm
from agent import memory_dashboard, chat_archive, memory, memory_embeddings

# Facts expected below are literal, deliberately fictional source information.
CASES = [
    ('employment', 'Beruflich bin ich selbstständig.', [('ich', 'selbstständig')], 'Wie ist mein beruflicher Status?'),
    ('health', 'Gesundheitlich bin ich beschwerdefrei.', [('ich', 'beschwerdefrei')], 'Wie ist mein gesundheitlicher Status?'),
    ('project_state', 'Mein Projekt Sternkarte ist im Testbetrieb.', [('projekte.sternkarte', 'Testbetrieb')], 'Welchen Status hat mein Projekt Sternkarte?'),
    ('past_state', 'Im Jahr 2021 war ich beruflich arbeitslos.', [('ich', 'arbeitslos')], 'Wie war mein beruflicher Status 2021?'),
    ('relationship', 'Meine Partnerin heißt Elara und arbeitet als Lehrerin.', [('partner', 'Elara'), ('partner', 'Lehrerin')], 'Wie heißt meine Partnerin und welchen Beruf hat sie?'),
    ('person', 'Meine Kollegin Maribel wohnt in Ulm und arbeitet als Architektin.', [('personen.maribel', 'Ulm'), ('personen.maribel', 'Architektin')], 'Wo wohnt meine Kollegin Maribel und welchen Beruf hat sie?'),
    ('technologies', 'Mein Projekt Sternkarte verwendet SQLite und Python.', [('projekte.sternkarte', 'SQLite'), ('projekte.sternkarte', 'Python')], 'Welche Technologien verwendet mein Projekt Sternkarte?'),
    ('hobbies', 'Meine Hobbys sind Rudern und Schach.', [('ich', 'Rudern'), ('ich', 'Schach')], 'Welche Hobbys habe ich?'),
    ('residence', 'Ich wohne in Erfurt.', [('ich', 'Erfurt')], 'Wo wohne ich?'),
    ('residence_conflict', 'Ich wohne in Jena.', [('ich', 'Jena')], 'Welche widersprüchlichen Wohnorte sind über mich gespeichert?'),
    ('plan', 'Ich plane, nächstes Jahr nach Kiel zu ziehen.', [('ich', 'Kiel')], 'Welchen Umzug plane ich?'),
    ('wish', 'In meiner Partnerschaft wünsche ich mir mehr gemeinsame Zeit.', [('ich', 'gemeinsame Zeit')], 'Was wünsche ich mir in meiner Partnerschaft?'),
    ('hypothesis', 'Wenn ich Pilot wäre, würde ich nach Rom fliegen.', [], 'Was ist mein Beruf?'),
    ('question', 'Ist meine Partnerin Ärztin?', [], 'Ist meine Partnerin Ärztin?'),
]


def run(args):
    records = json.loads(Path(args.replay).read_text())['responses'] if args.replay else {}
    report = {'date': datetime.now(timezone.utc).isoformat(), 'mode': 'live' if args.live else 'replay',
              'model': 'Qwen3.5-4B-MLX-4bit', 'cases': [], 'responses': records}
    expected = sum(len(c[2]) for c in CASES)
    with tempfile.TemporaryDirectory(prefix='nobby-fictional-e2e-') as tmp:
        root = Path(tmp)
        pm.DB_PATH = root/'personal.sqlite3'
        chat_archive.DB_PATH = root/'archive.sqlite3'
        memory.MEMORY_DB = root/'legacy.sqlite3'
        memory_dashboard.STATE_PATH = root/'control.json'
        # The targeted acceptance exercises lexical recall without another service.
        memory_embeddings.embedding_health = lambda **kwargs: None
        pm.set_enabled(True)
        smart.set_enabled(True)
        if args.live:
            mm.configure({'mode': 'dedicated', 'port': 8011, 'model': args.model})
        chats = {name: {'id': 'fictional-'+name, 'updated': i+1,
                       'messages': [{'role': 'user', 'content': text}]}
                 for i, (name, text, _, _) in enumerate(CASES)}
        smart._READER = lambda cid: next((c for c in chats.values() if c['id']==cid), None)
        smart._CHAT_LOCK = threading.RLock()
        def complete(payload):
            name = next(n for n,t,_,_ in CASES if t == json.loads(payload)['message'])
            if args.live:
                records[name] = mm.complete(smart.extraction_messages(payload, profile='compact'))
            return records[name]
        smart._COMPLETE = complete
        for name,text,targets,query in CASES:
            start = time.monotonic()
            smart.process_message('fictional-'+name, 0, smart._digest(text))
            raw = records.get(name, '')
            try:
                decoded = smart.decode_output(raw)
                candidates = decoded['facts']
                episode_candidates = decoded.get('episodes', [])
            except ValueError:
                candidates = []
                episode_candidates = []
            parsed = smart.parse_facts(raw,text)
            def matches(items, subject, token):
                return any(f.get('subject') == subject and token.casefold() in f.get('value','').casefold() for f in items)
            def episode_match(token, *, validated=False):
                return any(token.casefold() in e.get('description','').casefold()
                    and (not validated or (e.get('description','') in text
                         and e.get('evidence','') in text and e.get('status') in ('statement','plan')))
                    for e in episode_candidates)
            report['cases'].append({'name':name, 'expected':len(targets),
                'extracted':sum(matches(candidates,s,t) or episode_match(t) for s,t in targets),
                'validated':sum(matches(parsed,s,t) or episode_match(t, validated=True) for s,t in targets),
                'seconds':round(time.monotonic()-start,2), 'query':query})
            print(name, report['cases'][-1], flush=True)
        with pm._connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM facts WHERE status='active'")]
            conflicts = [dict(r) for r in conn.execute('SELECT c.*,f.subject,f.field FROM conflicts c JOIN facts f ON f.id=c.fact_id')]
            episodes = [dict(r) for r in conn.execute('SELECT * FROM episodes')]
            evidence = [dict(r) for r in conn.execute('SELECT e.*,s.chat_id FROM fact_evidence e JOIN memory_sources s ON s.id=e.source_id')]
            episode_evidence = [dict(r) for r in conn.execute('SELECT e.*,s.chat_id FROM episode_evidence e JOIN memory_sources s ON s.id=e.source_id')]
            job_states = dict(conn.execute('SELECT status,count(*) FROM analysis_jobs GROUP BY status'))
        stored=found=0
        for result, (name,text,targets,query) in zip(report['cases'],CASES):
            recalled = km.context(query)
            result['context'] = recalled
            result['stored'] = 0
            result['retrieved'] = 0
            for subject, token in targets:
                present = any(r['subject']==subject and token.casefold() in r['value'].casefold() for r in rows)
                present |= any(r['subject']==subject and token.casefold() in r['proposed_value'].casefold() for r in conflicts)
                present |= any(token.casefold() in r['description'].casefold()
                    and any(e['episode_id']==r['id'] and e['chat_id']=='fictional-'+name for e in episode_evidence)
                    for r in episodes)
                result['stored'] += int(present)
                result['retrieved'] += int(present and any(token.casefold() in line.casefold()
                    and 'source: chat fictional-'+name+' message 0' in line
                    for line in recalled.splitlines()))
            stored += result['stored']; found += result['retrieved']
        unsupported = sum(not any(e['fact_id']==r['id'] and r['value'].casefold() in e['evidence'].casefold() for e in evidence) for r in rows)
        # Current residence is single-valued; its second assertion is a real conflict.
        false_conflicts = sum(not (r['subject']=='ich' and r['field']=='wohnort' and r['proposed_value']=='Jena') for r in conflicts)
        report['metrics'] = {'expected':expected, 'extracted':sum(r['extracted'] for r in report['cases']),
            'validated':sum(r['validated'] for r in report['cases']), 'stored_including_review':stored,
            'retrieved_with_source':found, 'false_conflicts':false_conflicts,
            'real_conflicts':len(conflicts)-false_conflicts, 'unsupported_active_facts':unsupported,
            'negative_case_facts':sum(r['source_chat_id'] in ('fictional-hypothesis','fictional-question') for r in rows),
            'plan_labeled': any('Kiel' in line and ('(plan' in line or 'not completed' in line)
                for line in report['cases'][10]['context'].splitlines()),
            'jobs':job_states}
        report['fact_evidence'] = evidence
        report['episode_evidence'] = episode_evidence
        report['stored_facts'] = rows
        report['conflicts'] = conflicts
        report['episodes'] = episodes
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['metrics'],ensure_ascii=False),flush=True)
    if args.check:
        m = report['metrics']
        if (m['retrieved_with_source'] != expected or m['false_conflicts'] or m['real_conflicts']!=1
                or m['unsupported_active_facts'] or m['negative_case_facts'] or not m['plan_labeled'] or m['jobs'] != {'done':14}):
            raise SystemExit(1)

if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--live',action='store_true'); mode.add_argument('--replay')
    p.add_argument('--model', default=str(Path.home()/'Models/router/Qwen3.5-4B-MLX-4bit'))
    p.add_argument('--report',required=True); p.add_argument('--check',action='store_true')
    run(p.parse_args())
