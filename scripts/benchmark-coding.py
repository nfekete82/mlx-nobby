#!/usr/bin/env python3
"""Opt-in serial Model Scout coding benchmark of already-installed aliases.

Uses existing runtime switches, global lease, RAM admission and runtime lock.
Makes a private config backup before switching; always restores the baseline.
No downloads, auto-adoption, or model-generated code execution.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aliases', nargs='+', required=True)
    parser.add_argument('--runs', type=int, default=3, choices=range(1, 6))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--record-evaluations', action='store_true')
    args = parser.parse_args()
    from agent import app, model_evaluations
    from agent.model_scout_routes import benchmark_runtime, complete_local_model
    import runtime_coordinator
    models = app.load_models()
    selected = [next((m for m in models if m.get('alias') == alias), None) for alias in args.aliases]
    if any(model is None or complete_local_model(model) is None for model in selected):
        parser.error('Every alias must be registered and fully installed locally. No downloads allowed.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    backup = args.output.parent / ('private-config-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    report = {'schema': 1, 'suite': 'mlx-nobby-coding-v1', 'real_inference': True,
              'created_at': datetime.now(timezone.utc).isoformat(), 'runs': [],
              'limitations': ['Deterministic micro-suite; does not execute code or real tools.',
                             'RSS samples are not peak unified/Metal memory.',
                             'One cold/warm state per model; repeat runs for variance.']}
    original = None
    switched = False
    with runtime_coordinator.chat_runtime(), app.MODEL_RUNTIME_LOCK:
        try:
            config = app.load_config()
            original = next((m for m in models if m.get('repo') == config.get('MODEL')), None)
            if not original:
                raise RuntimeError('Cannot safely restore unregistered baseline')
            shutil.copy2(app.CONFIG, backup / 'config')
            (backup / 'config').chmod(0o600)
            port = int(config.get('PORT', 8000))
            report['baseline_alias'] = original['alias']
            for model in selected:
                runtime_coordinator.ensure_model_load_allowed('chat')
                load_started = time.perf_counter()
                if model['repo'] != app.load_config().get('MODEL'):
                    switched = True
                    app.switch_model_runtime(model['alias'])
                handoff = time.perf_counter() - load_started
                for run in range(args.runs):
                    result = benchmark_runtime(port, app.find_server_pid, suite='coding', model_id=model['repo'])
                    result.update(alias=model['alias'], run=run + 1, handoff_seconds=round(handoff, 3))
                    report['runs'].append(result)
                    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
                    print(json.dumps({'alias':model['alias'], 'run':run + 1, 'quality':result['quality'],
                                      'performance':result['performance']}), flush=True)
                    if args.record_evaluations:
                        model_evaluations.record(model['repo'], kind='coding', status='tested',
                            reason='Measured coding-v1 micro-suite; no automatic winner selection.',
                            metrics={'quality_score':result['quality']['score'], **result['performance']}, source='coding-v1')
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            try:
                if switched and original:
                    app.switch_model_runtime(original['alias'])
                    if app.CONFIG.read_bytes() != (backup / 'config').read_bytes():
                        shutil.copy2(backup / 'config', app.CONFIG)
                    report['baseline_restored'] = app.load_config().get('MODEL') == original['repo']
            finally:
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
