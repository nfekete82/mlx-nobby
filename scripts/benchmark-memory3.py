#!/usr/bin/env python3
"""CPU-only, fictional recall benchmark; never opens production memory or models.

Run this same script/fixture on both revisions for an A/B comparison. Metrics
evaluate retrieved evidence, not generated answers or actual model quality.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import resource
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(*, distractors=2000, repeats=3):
    # Imports inside isolation prevent module initialization from using home.
    with tempfile.TemporaryDirectory(prefix='mlx-memory3-bench-') as directory, ExitStack() as stack:
        root = Path(directory)
        stack.enter_context(patch.object(Path, 'home', return_value=root))
        from agent import knowledge_memory as km, personal_memory as pm
        from agent import memory, memory_dashboard, memory_embeddings, memory_commands
        for module, key, value in [(pm, 'DB_PATH', root/'personal.sqlite3'),
                                  (memory, 'MEMORY_DB', root/'legacy.sqlite3'),
                                  (memory_dashboard, 'STATE_PATH', root/'control.json')]:
            stack.enter_context(patch.object(module, key, value))
        stack.enter_context(patch.object(memory_embeddings, 'embedding_health', return_value=None))
        corpus = json.loads((ROOT/'tests/fixtures/memory3_retrieval.json').read_text())
        pm.set_enabled(True)
        receipts = []
        for key, statement in corpus['sources'].items():
            receipts.append(memory_commands.execute([{'role': 'user', 'content': 'Merk dir: '+statement}], chat_id='fictional-'+key)['persisted'])
        with pm._connect() as conn:
            pm._schema(conn)
            for index in range(distractors):
                conn.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (f'distractor-{index}', 'ich', f'notiz.fixture{index}',
                              f'Fiktiver Katalogeintrag Nummer {index} mit Kennung K{index}.',
                              0, 'fictional-noise', index, 'active', index+1, index+1))
        latencies = []
        cases = []
        for target, query in corpus['queries']:
            for _ in range(repeats):
                start = time.perf_counter()
                context = km.context(query, semantic=False)
                latencies.append((time.perf_counter()-start)*1000)
            hits = re.findall(r'^- \[fact:([^\]]+)\].*?\(source: ([^\n]+)', context, re.M)[:5]
            relevant = [i+1 for i, (_, source) in enumerate(hits) if f'chat fictional-{target} message' in source]
            cases.append({'case': len(cases)+1, 'target': target, 'recall_at_5': int(bool(relevant)),
                          'precision_at_5': len(relevant)/5, 'reciprocal_rank': 1/min(relevant) if relevant else 0,
                          'hits': len(hits), 'sourced_hits': sum('chat fictional-' in s for _, s in hits)})
        negatives = [not re.search(r'^- \[fact:', km.context(q), re.M) for q in corpus['negative_queries']]
        explicit_times = []
        from agent import memory_lifecycle
        from agent import chat_archive
        stack.enter_context(patch.object(chat_archive, 'DB_PATH', root/'archive.sqlite3'))
        assembly_recall = []
        for target, q in corpus['queries']:
            start = time.perf_counter()
            messages = memory_lifecycle.fast_personal_context([{'role': 'user', 'content': q}])
            explicit_times.append((time.perf_counter()-start)*1000)
            assembled = '\n'.join(m['content'] for m in messages if m['role']=='system')
            assembly_recall.append(f'chat fictional-{target} message' in assembled)
        normal_times = []
        for _ in range(32):
            start = time.perf_counter()
            memory_lifecycle.enrich_messages([{'role':'user','content':'Hilf mir mit meinem Browserspiel.'}],observe=False)
            normal_times.append((time.perf_counter()-start)*1000)
        def timing(values):
            ordered = sorted(values)
            return {'p50_ms': round(statistics.median(values), 3),
                    'p95_ms': round(ordered[min(len(ordered)-1, int(.95*len(ordered)))], 3)}
        return {'date': datetime.now(timezone.utc).isoformat(), 'fixture': 'memory3_retrieval.json',
                'mode': 'CPU lexical; embeddings unavailable; no live extraction/answer model',
                'distractors': distractors, 'cases': cases,
                'metrics': {'recall_at_5': statistics.mean(c['recall_at_5'] for c in cases),
                            'precision_at_5': statistics.mean(c['precision_at_5'] for c in cases),
                            'mrr': statistics.mean(c['reciprocal_rank'] for c in cases),
                            'source_attribution': sum(c['sourced_hits'] for c in cases)/max(1,sum(c['hits'] for c in cases)),
                            'explicit_save_success': sum(receipts)/len(receipts),
                            'new_chat_context_recall': sum(assembly_recall)/len(assembly_recall),
                            'negative_evidence_abstention': sum(negatives)/len(negatives)},
                'retrieval': timing(latencies), 'fast_context_assembly': timing(explicit_times),
                'normal_context_assembly': timing(normal_times),
                'process_maxrss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
                'live_model_faithfulness': None, 'live_model_hallucination_rate': None,
                'gpu_ram_swap_under_load': None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--distractors', type=int, default=2000)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 0 <= args.distractors <= 100000 or not 1 <= args.repeats <= 100:
        parser.error('distractors must be 0..100000 and repeats 1..100')
    report = run(distractors=args.distractors, repeats=args.repeats)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}, indent=2))
