#!/usr/bin/env python3
"""Direct LTX visual benchmark; frozen conditioning bytes, no audio processing."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from agent import talking_photo_ltx as ltx
import runtime_coordinator

SEEDS = [42, 123, 256, 512, 1024, 1337, 2026, 4096, 12345, 54321]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')

def check_inputs(root, manifest):
    for name, expected in manifest['hashes'].items():
        if digest(root / name) != expected:
            raise ValueError(f'Frozen input changed: {name}')

def selected_seed(root):
    for seed in SEEDS:
        path = root/f'seed-{seed}'/'parameters.json'
        if not path.exists() or json.loads(path.read_text())['status'] != 'completed':
            raise ValueError('Complete the entire seed sweep before varying parameters')
    selection = json.loads((root/'selection.json').read_text())
    if selection['best_seed'] not in SEEDS:
        raise ValueError('Selected seed must be part of the completed sweep')
    return selection['best_seed']

def command(root, folder, parameters, manifest):
    check_inputs(root, manifest)
    cmd = [str(ltx.RUNTIME_PYTHON), str(ltx.RUNNER)]
    values = dict(model=manifest['model'], image=str(root/'image.png'),
                  audio=str(root/'conditioning.wav'), output=str(folder/'output.mp4'),
                  diagnostics=str(folder/'runner.json'), **parameters)
    for key, value in values.items():
        cmd.extend(['--' + key.replace('_', '-'), str(value)])
    return cmd

def viewer(root):
    cards = []
    recommendation_path = root/'recommendation.json'
    recommendation = json.loads(recommendation_path.read_text()) if recommendation_path.exists() else None
    summary = ''
    if recommendation:
        chosen = recommendation['production_recommendation']
        summary = (f'<p><strong>Empfehlung für diese Referenz: Seed {recommendation["best_seed"]}, '
                   f'{chosen["stage1_steps"]}/{chosen["stage2_steps"]} Steps, '
                   f'CFG {chosen["cfg_scale"]}, STG {chosen["stg_scale"]}, {chosen["fps"]} FPS.</strong> '
                   '<a href="recommendation.json">Vollständige Empfehlung</a></p>')
    def order(path):
        p = json.loads(path.read_text())['parameters']
        return (0 if path.parent.name == f'seed-{p["seed"]}' else 1, p['seed'], path.parent.name)
    for path in sorted(root.glob('*/parameters.json'), key=order):
        data = json.loads(path.read_text())
        name = path.parent.name
        badge = ' · EMPFOHLEN' if recommendation and name == recommendation['best_run'] else ''
        p = data['parameters']
        stage2 = str(p['stage2_steps'])
        if p['stage2_steps'] > 3:
            stage2 += ' angefordert, 3 effektiv'
        ready = data['status'] == 'completed'
        metrics_path = path.parent/'metrics.json'
        metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
        extra = ''
        if metrics and not metrics.get('landmark_failure'):
            extra = (f'<p>Mundvariation ab Frame 8: {metrics["settled_mouth_excursion"]:.4f} · '
                f'Kopfversatz P95: {metrics["head_translation_p95_pixels"]:.1f} px · '
                f'Flicker-Proxy: {metrics["skin_flicker_second_difference"]:.2f}</p>'
                f'<p><a href="{name}/contact-sheet.jpg">Gesichtsverlauf</a> · '
                f'<a href="{name}/mouth-all-frames.jpg">Alle 81 Mund-Frames</a> · '
                f'<a href="{name}/metrics.json">Messwerte</a></p>')
        cards.append(f'<article><h2>{html.escape(name)} · Seed {p["seed"]}{badge}</h2>'
            f'<p>Steps {p["stage1_steps"]}/{stage2} · CFG {p["cfg_scale"]} · STG {p["stg_scale"]}</p>'
            + (f'<video controls preload="metadata" muted src="{name}/output.mp4"></video>' if ready else '<p>Render läuft / ausstehend</p>')
            + extra + f'<p><a href="{name}/parameters.json">Parameter</a> · <a href="{name}/runner.json">LTX-Diagnose</a></p></article>')
    (root/'index.html').write_text('''<!doctype html><html lang="de"><meta charset="utf-8"><title>LTX Lippenvergleich</title>
<style>body{font:16px system-ui;background:#151821;color:#eee;margin:24px}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article{background:#252b38;padding:14px}video{width:100%}a{color:#9ccaff}button{padding:12px;margin:8px}p{line-height:1.4}</style>
<h1>LTX 2.5 · identisches Bild und Conditioning-WAV</h1><p>24 FPS, 81 Frames. Native Geschwindigkeit. Seed-Sweep: 15/3 Steps, CFG 3,0, STG 1,0. Parameterläufe ändern jeweils genau eine Variable.</p>
<p>Landmark-Bewegung und Bilddifferenzen sind relative Diagnosen, keine phonemgenaue Synchronitäts- oder Identitätsmessung.</p>
<audio id="audio" controls src="conditioning.wav"></audio><button onclick="start()">Alle ab Anfang abspielen</button><button onclick="stop()">Alle pausieren</button>
<p>Gemeinsame Frameposition: <input type="range" min="0" max="80" step="1" value="0" oninput="seek(this.value)"><span id="frame">0 / 0,000 s</span></p>
<p><a href="inputs.json">Eingaben und Hashes</a> · <a href="assessment.json">Messwerte / Bewertung</a> · <a href="selection.json">Seed-Auswahl</a> · <a href="REPORT.md">Ergebnisbericht</a></p>'''+summary+'<section>'+''.join(cards)+'''</section><script>
const audio=document.getElementById('audio');
function start(){document.querySelectorAll('video').forEach(v=>{v.currentTime=0;v.play()});audio.currentTime=0;audio.play()}
function stop(){document.querySelectorAll('video').forEach(v=>v.pause());audio.pause()}
function seek(frame){stop();const t=Number(frame)/24;document.querySelectorAll('video').forEach(v=>v.currentTime=t);audio.currentTime=t;document.getElementById('frame').textContent=frame+' / '+t.toFixed(3)+' s'}
</script></html>''')

def run(root, name, parameters, manifest):
    folder = root/name
    folder.mkdir(exist_ok=True)
    record = folder/'parameters.json'
    if record.exists():
        previous = json.loads(record.read_text())
        if previous['parameters'] != parameters:
            raise ValueError('Cannot overwrite a different experiment')
        if previous['status'] == 'completed':
            check_inputs(root, manifest)
            if digest(folder/'output.mp4') != previous['output_sha256']:
                raise ValueError('Completed output changed')
            return
    cmd = command(root, folder, parameters, manifest)
    data = dict(parameters=parameters, command=cmd, input_hashes=manifest['hashes'], status='rendering')
    save(record, data)
    viewer(root)
    print(f'START {name}', flush=True)
    started = time.monotonic()
    with (folder/'render.log').open('w') as log:
        with runtime_coordinator.video_runtime(ltx._CancelProxy(lambda: False),
                chat_loaded=ltx._chat_loaded, chat_command=ltx._chat_command):
            result = subprocess.run(cmd, cwd=ltx.RUNTIME_ROOT, stdout=log, stderr=subprocess.STDOUT)
    check_inputs(root, manifest)
    data.update(elapsed_seconds=round(time.monotonic()-started, 2),
                status='completed' if result.returncode == 0 else 'failed', returncode=result.returncode)
    if result.returncode == 0:
        actual = json.loads((folder/'runner.json').read_text())
        if actual['conditioning_audio_sha256'] != manifest['hashes']['conditioning.wav']:
            raise ValueError('LTX received different audio')
        data['output_sha256'] = digest(folder/'output.mp4')
    save(record, data)
    viewer(root)
    print(f'END {name}: {data["status"]} ({data["elapsed_seconds"]}s)', flush=True)
    if result.returncode:
        raise RuntimeError(f'Render failed: {folder}/render.log')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--baseline', type=Path, help='Saved successful debug bundle; required for first run')
    p.add_argument('--phase', choices=['prepare', 'seeds', 'parameters', 'repeat'], default='seeds')
    p.add_argument('--seed', type=int)
    args = p.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (root/'inputs.json').exists():
        if args.baseline is None:
            p.error('--baseline required for first run')
        source = json.loads((args.baseline/'render.json').read_text())
        for old, new in [('ltx-quality-source.png','image.png'),('ltx-quality-audio.wav','conditioning.wav')]:
            shutil.copyfile(args.baseline/old,root/new)
        baseline = dict(prompt=source['prompt'], negative_prompt=source['negative_prompt'],
            width=source['width'], height=source['height'], frames=source['frames'], fps=source['fps'],
            seed=42, stage1_steps=source['stage_1_steps'], stage2_steps=source['stage_2_steps'],
            cfg_scale=source['cfg_scale'], stg_scale=source['stg_scale'])
        save(root/'inputs.json',dict(source=str(args.baseline.resolve()),
            commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip(),
            hashes={n:digest(root/n) for n in ['image.png','conditioning.wav']}, baseline=baseline,
            model=str(ltx.MODEL_DIR), audio_processing='none; byte-for-byte copy of saved LTX input'))
    manifest = json.loads((root/'inputs.json').read_text())
    check_inputs(root,manifest)
    baseline = manifest['baseline']
    if baseline['fps'] != 24:
        raise ValueError('Benchmark requires 24 FPS')
    if args.phase == 'prepare':
        viewer(root)
    elif args.phase == 'seeds':
        for seed in SEEDS:
            run(root,f'seed-{seed}',dict(baseline,seed=seed),manifest)
    elif args.phase == 'repeat':
        seed = 42 if args.seed is None else args.seed
        run(root,f'seed-{seed}-repeat',dict(baseline,seed=seed),manifest)
    else:
        seed = selected_seed(root)
        if args.seed is not None and args.seed != seed:
            raise ValueError('Parameter phase must use the selected seed')
        for key, values in [('stage1_steps',[20,25]),('stage2_steps',[4,5]),('cfg_scale',[2.7,3.3]),('stg_scale',[0.8,1.2])]:
            for value in values:
                parameters = dict(baseline,seed=seed)
                parameters[key] = value
                assert sum(parameters[k] != dict(baseline,seed=seed)[k] for k in parameters) == 1
                run(root,f'{key}-{value}-seed-{seed}',parameters,manifest)

if __name__ == '__main__':
    main()
