#!/usr/bin/env python3
"""Offline, bounded-memory video diagnostics. Never loads a generation model.

Use image-venv/bin/python (NumPy, SciPy, Pillow) plus FFmpeg/ffprobe.
Adjacent-frame SSIM measures change, not identity or perceptual correctness.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

SAMPLE_TIMES = (0, 3, 5.9, 6.1, 7.9, 8.1, 9.9)
# First new frame follows the inclusive initial 145-frame clip.
BOUNDARY_FRAMES = (145, 193)


def run(command, timeout=180):
    return subprocess.run(command, check=True, capture_output=True, timeout=timeout).stdout


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def ssim(a, b):
    """Wang-style local SSIM: Gaussian 11x11, sigma 1.5, population covariance.

    Luma in [0,255], K1=.01, K2=.03. Crop five border pixels.
    No motion compensation: intended movement also reduces this score.
    """
    a, b = a.astype(np.float32), b.astype(np.float32)
    blur = lambda x: gaussian_filter(x, sigma=1.5, truncate=3.5)
    ma, mb = blur(a), blur(b)
    va, vb, cov = blur(a*a)-ma*ma, blur(b*b)-mb*mb, blur(a*b)-ma*mb
    score = ((2*ma*mb+6.5025)*(2*cov+58.5225) /
             ((ma*ma+mb*mb+6.5025)*(va+vb+58.5225)))
    return float(score[5:-5, 5:-5].mean())


def sharpness(a):
    a = a.astype(np.float32)
    lap = a[:-2,1:-1]+a[2:,1:-1]+a[1:-1,:-2]+a[1:-1,2:]-4*a[1:-1,1:-1]
    return float(lap.var())


def summarize(values):
    return {key: float(value) for key, value in zip(
        ('min', 'median', 'p95', 'max'), np.percentile(values, [0, 50, 95, 100]))} if values else None


def probe(path):
    metadata = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                               '-of', 'json', str(path)]))
    frames = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time',
        '-of', 'json', str(path)]))['frames']
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    audio = next((s for s in metadata['streams'] if s['codec_type'] == 'audio'), None)
    pts = [float(f['best_effort_timestamp_time']) for f in frames]
    fps = float(Fraction(video['avg_frame_rate']))
    period = 1/fps
    gaps = [{'frame': i, 'delta_seconds': pts[i]-pts[i-1]} for i in range(1,len(pts))
            if abs(pts[i]-pts[i-1]-period) > period*.1]
    duration = float(video.get('duration') or (pts[-1]-pts[0]+period))
    astart = float(audio.get('start_time', 0)) if audio else None
    aduration = float(audio['duration']) if audio and audio.get('duration') else None
    return {'width': int(video['width']), 'height': int(video['height']), 'fps': fps,
        'frames': len(pts), 'video_duration': duration,
        'container_duration': float(metadata['format']['duration']),
        'video_start': pts[0], 'audio_start': astart, 'audio_duration': aduration,
        'av_start_offset_seconds': astart-pts[0] if audio else None,
        'av_end_offset_seconds': astart+aduration-pts[0]-duration if aduration else None,
        'audio_sample_rate': audio.get('sample_rate') if audio else None,
        'codec': video['codec_name'], 'pixel_format': video['pix_fmt'],
        'pts_anomalies': gaps, 'pts': pts}


def frame_metrics(path, info, max_side=512):
    scale = min(1, max_side/max(info['width'], info['height']))
    width, height = max(16,round(info['width']*scale)), max(16,round(info['height']*scale))
    command = ['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path), '-an',
        '-vf', f'scale={width}:{height}:flags=area', '-fps_mode', 'passthrough',
        '-pix_fmt', 'gray', '-f', 'rawvideo', '-']
    rows, previous = [], None
    # Stderr goes to a temporary file: no full-video RAM buffer and no pipe deadlock.
    import tempfile
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:
            while True:
                raw = process.stdout.read(width*height)
                if not raw:
                    break
                if len(raw) != width*height:
                    raise RuntimeError('Truncated raw frame')
                current = np.frombuffer(raw, np.uint8).reshape(height,width)
                row = {'frame': len(rows), 'time': info['pts'][len(rows)],
                       'laplacian_variance': sharpness(current), 'mean_luma': float(current.mean())}
                if previous is not None:
                    row.update(adjacent_ssim=ssim(previous,current),
                        adjacent_mae=float(np.abs(current.astype(np.float32)-previous).mean()))
                rows.append(row)
                previous = current
            if process.wait(timeout=20):
                errors.seek(0)
                raise RuntimeError(errors.read().decode(errors='replace')[-2000:])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
    if len(rows) != info['frames']:
        raise RuntimeError('Decoded frame count differs from probe')
    # Native decoded YUV hashes: duplicate detection is independent of analysis scaling.
    hashes = run(['ffmpeg','-v','error','-threads','1','-i',str(path),'-map','0:v:0',
                  '-fps_mode','passthrough','-f','framemd5','-']).decode()
    hashes = [line.rsplit(',',1)[-1].strip() for line in hashes.splitlines()
              if line and not line.startswith('#')]
    duplicates = [i for i in range(1,len(hashes)) if hashes[i] == hashes[i-1]]
    baseline = [r['adjacent_mae'] for r in rows[1:] if all(abs(r['frame']-b)>12 for b in BOUNDARY_FRAMES)]
    median = float(np.median(baseline)) if baseline else 0
    seams = []
    for b in BOUNDARY_FRAMES:
        if b >= len(rows):
            continue
        seams.append({**rows[b], 'previous_frame': b-1,
            'mae_to_nonboundary_median_ratio': rows[b]['adjacent_mae']/median if median > 1e-6 else None,
            'window': rows[max(1,b-3):b+4]})
    return {'analysis_width': width, 'analysis_height': height,
        'adjacent_ssim': summarize([r['adjacent_ssim'] for r in rows[1:]]),
        'adjacent_mae': summarize([r['adjacent_mae'] for r in rows[1:]]),
        'laplacian_variance': summarize([r['laplacian_variance'] for r in rows]),
        'exact_duplicate_frames': duplicates, 'boundaries': seams, 'per_frame': rows}


def samples(path, info, directory):
    directory.mkdir()
    indices = {min(range(len(info['pts'])), key=lambda i:abs(info['pts'][i]-t)) for t in SAMPLE_TIMES}
    indices.update(i for b in BOUNDARY_FRAMES for i in (b-1,b) if i < info['frames'])
    selected = sorted(indices)
    expression = '+'.join(f'eq(n,{i})' for i in selected)
    run(['ffmpeg','-v','error','-i',str(path),'-vf',f'select=\'{expression}\'',
         '-fps_mode','passthrough',str(directory/'sample-%03d.png')])
    results=[]
    for sequence,index in enumerate(selected,1):
        source=directory/f'sample-{sequence:03}.png'
        target=directory/f'frame-{index:03}.png'
        source.rename(target)
        results.append({'frame': index, 'time': info['pts'][index], 'image': str(target.name)})
    sheet=Image.new('RGB',(240*len(results),340),'#171a22')
    draw=ImageDraw.Draw(sheet)
    for i,sample in enumerate(results):
        with Image.open(directory/sample['image']) as im:
            im.thumbnail((236,305))
            sheet.paste(im,(i*240+(240-im.width)//2,5))
        draw.text((i*240+5,318),f"{sample['time']:.4f}s / frame {sample['frame']}",fill='white')
    sheet.save(directory/'contact-sheet.jpg',quality=94)
    return results


def face_geometry(helper, directory, frames):
    if not helper:
        return {'status':'not_measured', 'reason':'No CPU Vision helper supplied; identity is unmeasured.'}
    try:
        detections=json.loads(run([str(helper),*[str(directory/f['image']) for f in frames]]))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {'status':'unavailable', 'reason':type(error).__name__,
                'limitations':'Vision can require execution outside the macOS sandbox. Technical diagnostics remain available.'}
    if len(detections) != len(frames):
        raise RuntimeError('Vision returned an unexpected number of observations')
    rows=[]
    for frame,detection in zip(frames,detections):
        row={**frame,**detection, 'face_count':len(detection['faces'])}
        if len(detection['faces'])==1:
            face=detection['faces'][0]
            points=face['landmarks']
            w,h=face['bounding_box'][2:]
            # Vision points are normalized within the face box; correct its aspect ratio.
            pixel=lambda name: np.asarray(points[name])*np.array([w,h])
            if points.get('leftEye') and points.get('rightEye'):
                left,right=pixel('leftEye'),pixel('rightEye')
                row['interocular_over_face_width']=float(np.linalg.norm(left.mean(0)-right.mean(0))/w)
                for name,p in [('left',left),('right',right)]:
                    row[name+'_eye_height_over_width']=float(np.ptp(p[:,1])/max(1e-9,np.ptp(p[:,0])))
            if points.get('outerLips'):
                row['mouth_width_over_face_width']=float(np.ptp(pixel('outerLips')[:,0])/w)
        rows.append(row)
    changes=[]
    for previous,current in zip(rows,rows[1:]):
        changes.append({'from_frame':previous['frame'], 'to_frame':current['frame'],
            'seconds':current['time']-previous['time'],
            'delta':{key:current[key]-previous[key] for key in (
                'interocular_over_face_width','left_eye_height_over_width',
                'right_eye_height_over_width','mouth_width_over_face_width')
                if key in previous and key in current}})
    crops=[]
    for row in rows:
        if len(row['faces']) != 1:
            continue
        with Image.open(directory/row['image']) as im:
            x,y,w,h=row['faces'][0]['bounding_box']
            bounds=(max(0,int(x-w*.15)),max(0,int(im.height-y-h*1.15)),
                    min(im.width,int(x+w*1.15)),min(im.height,int(im.height-y+h*.15)))
            crop=im.crop(bounds)
            crop_name=f"face-{row['frame']:03}.png"
            crop.save(directory/crop_name)
            row['face_crop']=crop_name
            crop.thumbnail((240,240))
            crops.append((row,crop.copy()))
    if crops:
        sheet=Image.new('RGB',(240*len(crops),270),'#171a22')
        draw=ImageDraw.Draw(sheet)
        for index,(row,crop) in enumerate(crops):
            sheet.paste(crop,(index*240+(240-crop.width)//2,0))
            draw.text((index*240+4,248),f"{row['time']:.4f}s / frame {row['frame']}",fill='white')
        sheet.save(directory/'face-contact-sheet.jpg',quality=94)
    return {'status':'measured', 'backend':'Apple Vision CPU VNDetectFaceLandmarksRequest',
            'limitations':'Sparse samples; pose, blinking, expression and detector noise affect geometry. No identity embeddings or identity score.',
            'samples':rows, 'sample_changes':changes, 'face_crops_available':bool(crops)}


def job_telemetry(path):
    if not path:
        return None
    d=json.loads(Path(path).read_text())
    payload=d.get('payload',{})
    result={k:d.get(k) for k in ('id','status','error','resolved_model','memory_before','memory_peak','memory_after',
        'memory_admission','memory_before_admission','runtime_handoff','rolling_stage_memory')}
    result['generation_seconds']=(d['finished_at']-d['started_at']
        if d.get('finished_at') and d.get('started_at') else None)
    result['settings']={k:payload.get(k) for k in ('seed','resolution','aspect_ratio','fps','duration','identity_lock','resize_mode')}
    if payload.get('i2v_image_crf') is not None:
        result['settings']['i2v_image_crf']=payload['i2v_image_crf']
    result['prompt_sha256']=hashlib.sha256(payload.get('prompt','').encode()).hexdigest()
    source=payload.get('first_frame')
    result['source_sha256']=sha256(source) if source and Path(source).is_file() else None
    return result


def benchmark(label,path,out,job=None,helper=None):
    started=time.monotonic()
    info=probe(path)
    metrics=frame_metrics(path,info)
    frames=samples(path,info,out/label)
    faces=face_geometry(helper,out/label,frames)
    shutil.copyfile(path,out/label/'video.mp4')
    source_preview=None
    if job:
        source=json.loads(Path(job).read_text()).get('payload',{}).get('first_frame')
        if source and Path(source).is_file() and Path(source).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
            source_preview='source'+Path(source).suffix.lower()
            shutil.copyfile(source,out/label/source_preview)
    return {'label':label,'file_name':Path(path).name,'sha256':sha256(path),
        'bytes':Path(path).stat().st_size,'technical':{k:v for k,v in info.items() if k!='pts'},
        'metrics':metrics,'samples':frames,'face_geometry':faces,'job':job_telemetry(job),
        'source_preview':source_preview,
        'analysis_seconds':round(time.monotonic()-started,2),
        'visual_assessment':{'status':'requires_human_review','identity':'unmeasured'}}


def write_report(out,results):
    comparisons=[]
    for index,left in enumerate(results):
        for right in results[index+1:]:
            a,b=left.get('job') or {},right.get('job') or {}
            checks={key:(a.get(key)==b.get(key) if a.get(key) is not None and b.get(key) is not None else None)
                    for key in ('source_sha256','prompt_sha256','settings','resolved_model')}
            comparisons.append({'left':left['label'],'right':right['label'], 'input_checks':checks,
                'matched_recorded_inputs':all(value is True for value in checks.values()),
                'limits':'Runtime, hardware and effective conditioning must also match; inspect provenance and implementation.'})
    report={'schema_version':1,'ffmpeg_version':run(['ffmpeg','-version']).decode().splitlines()[0],
        'methodology':{'ssim':'Gaussian local luma SSIM, sigma=1.5, 11x11; no motion compensation',
            'analysis':'Area downsample max side 512; full-resolution YUV hashes for duplicates; native PNG review frames.',
            'limits':'SSIM rewards stillness; sharpness rewards noise too. Geometry changes can reflect desired motion. A/V offsets measure stream timing, not lip sync. Different resolutions are not controlled A/B.',
            'boundary_frames':list(BOUNDARY_FRAMES),'requested_sample_times':list(SAMPLE_TIMES)},
            'comparison_pairs':comparisons, 'videos':results}
    (out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    body=['<!doctype html><meta charset="utf-8"><title>LTX quality comparison</title>',
          '<style>body{font:16px system-ui;background:#10131b;color:#eee;margin:32px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #596070}img{max-width:100%}a{color:#8bd}pre{white-space:pre-wrap}</style>',
          '<h1>LTX quality comparison</h1><p>Technical measurements and visual review are separate. No metric here proves identity or natural blinking. Geometry is affected by pose and expression. Stream timing does not prove lip sync.</p>',
          '<table><tr><th>Video</th><th>Canvas / frames / FPS</th><th>Video / audio duration</th><th>Adjacent SSIM median</th><th>Duplicates / PTS errors</th><th>Generation time</th></tr>']
    for r in results:
        t,m=r['technical'],r['metrics']
        body.append(f"<tr><td>{html.escape(r['label'])}</td><td>{t['width']}×{t['height']} / {t['frames']} / {t['fps']}</td><td>{t['video_duration']} / {t['audio_duration']}</td><td>{m['adjacent_ssim']['median']:.5f}</td><td>{len(m['exact_duplicate_frames'])} / {len(t['pts_anomalies'])}</td><td>{(r.get('job') or {}).get('generation_seconds')}</td></tr>")
    body.extend(['</table>','<h2>Input comparability</h2><pre>'+html.escape(json.dumps(comparisons,indent=2))+'</pre>'])
    for r in results:
        label=html.escape(r['label'])
        body.extend([f'<h2>{label}</h2>',f'<a href="{label}/contact-sheet.jpg"><img src="{label}/contact-sheet.jpg"></a>',
            f'<p><video controls preload="metadata" style="max-height:70vh;max-width:100%" src="{label}/video.mp4"></video></p>',
            (f'<details><summary>Original source</summary><img style="max-height:70vh" src="{label}/{html.escape(r["source_preview"])}"></details>' if r.get('source_preview') else ''),
            '<p>Native frames: '+ ' · '.join(f'<a href="{label}/{f["image"]}">{f["time"]:.4f}s</a>' for f in r['samples'])+'</p>',
            (f'<h3>Native face crops</h3><img src="{label}/face-contact-sheet.jpg">' if r['face_geometry'].get('face_crops_available') else ''),
            '<h3>Exact segment joins</h3><pre>'+html.escape(json.dumps(r['metrics']['boundaries'],indent=2))+'</pre>',
            '<h3>Face geometry (observations, no identity verdict)</h3><pre>'+html.escape(json.dumps(r['face_geometry'],indent=2))+'</pre>'])
    body.append('<p><a href="report.json">Complete reproducible measurements</a></p>')
    (out/'index.html').write_text('\n'.join(body))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('videos',nargs='+',help='label=/absolute/video.mp4')
    parser.add_argument('--job',action='append',default=[],help='label=/absolute/job.json')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--vision-helper',type=Path)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    jobs=dict(x.split('=',1) for x in args.job)
    results=[]
    labels=set()
    for item in args.videos:
        label,path=item.split('=',1)
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',label) or label in labels:
            parser.error('Labels must be unique and contain only letters, digits, underscores and hyphens')
        labels.add(label)
        results.append(benchmark(label,Path(path),args.out,jobs.get(label),args.vision_helper))
        print(label,'analyzed',flush=True)
    write_report(args.out,results)
    print(args.out/'index.html')


if __name__=='__main__':
    main()
