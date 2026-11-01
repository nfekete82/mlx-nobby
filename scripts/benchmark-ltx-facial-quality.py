#!/usr/bin/env python3
"""Local CPU-only facial video audit and synchronized native-frame viewer.

No generation, model download, face recognition, restoration or acceptance score.
Use image-venv (NumPy/SciPy/Pillow), FFmpeg and optional CPU Vision helper.
"""
import argparse
import html
import importlib.util
import json
import platform
import subprocess
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw


def load_module(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


quality=load_module('video_quality','benchmark-video-quality.py')
segments=load_module('face_segments','analyze-ltx-face-segments.py')


def lab_d65(rgb):
    """sRGB -> CIELAB using D65 reference white; uncalibrated image diagnostics."""
    rgb=np.asarray(rgb,dtype=float)/255
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]])@linear
    xyz=xyz/np.array([.95047,1,1.08883])
    delta=6/29
    f=np.where(xyz>delta**3,np.cbrt(xyz),xyz/(3*delta*delta)+4/29)
    return np.array([116*f[1]-16,500*(f[0]-f[1]),200*(f[1]-f[2])])


def registered_change(previous,current,max_shift=8):
    """Translation registration of normalized face luma, not optical flow.

    Rotation, expression and occlusion remain residuals. The response is a
    diagnostic only, never a flicker/identity classifier.
    """
    a,b=previous.astype(float),current.astype(float)
    if a.shape != b.shape or a.ndim != 2:
        raise ValueError('Registration requires equal two-dimensional arrays')
    if min(a.std(), b.std()) < 1e-6:
        return {'status':'insufficient_texture'}
    window=np.outer(np.hanning(a.shape[0]),np.hanning(a.shape[1]))
    fa=np.fft.fft2((a-a.mean())*window);fb=np.fft.fft2((b-b.mean())*window)
    cross=fa*np.conj(fb);cross/=np.maximum(np.abs(cross),1e-12)
    correlation=np.fft.ifft2(cross).real
    peak=np.unravel_index(np.argmax(correlation),correlation.shape)
    shift=np.array(peak,dtype=int)
    for axis,size in enumerate(a.shape):
        if shift[axis]>size//2:shift[axis]-=size
    if correlation[peak] < .05 or np.max(np.abs(shift))>max_shift:return {'status':'registration_uncertain','shift_yx':shift.tolist()}
    corrected=np.roll(b,tuple(shift),axis=(0,1));interior=(slice(12,-12),slice(12,-12))
    return {'status':'measured','shift_yx':shift.tolist(),'peak':float(correlation[peak]),
        'raw_luma_mae':float(np.abs(a[interior]-b[interior]).mean()),
        'registered_luma_mae':float(np.abs(a[interior]-corrected[interior]).mean())}


def face_features(directory,geometry):
    rows=[];previous=None;previous_center=None;previous_step=None;previous_lab=None
    for sample in geometry['samples']:
        row={'frame':sample['frame'],'time':sample['frame']/24,'face_count':len(sample['faces'])}
        if len(sample['faces'])!=1:
            row['status']='missing_or_multiple_faces';previous=previous_center=previous_step=previous_lab=None
            rows.append(row);continue
        face=sample['faces'][0];x,y,w,h=face['bounding_box']
        if face['confidence'] < .8 or min(w,h) <= 0:
            row['status']='low_confidence_or_invalid_box';previous=previous_center=previous_step=previous_lab=None
            rows.append(row);continue
        row.update(segments.eye_observations(face));row['confidence']=face['confidence']
        row['yaw_degrees']=np.degrees(face['yaw']) if face.get('yaw') is not None else None
        row['roll_degrees']=np.degrees(face['roll']) if face.get('roll') is not None else None
        center=np.array([x+w/2,y+h/2]);row['center_xy']=center.tolist();row['box_wh']=[w,h]
        if previous_center is not None:
            step=center-previous_center
            row['center_step_over_face_width']=float(np.linalg.norm(step)/w)
            if previous_step is not None:row['center_acceleration_over_face_width']=float(np.linalg.norm(step-previous_step)/w)
            previous_step=step
        previous_center=center
        with Image.open(directory/sample['image']) as im:
            # Vision coordinates use bottom-left; PNG uses top-left.
            bounds=(max(0,int(x)),max(0,int(im.height-y-h)),min(im.width,int(x+w)),min(im.height,int(im.height-y)))
            crop=im.crop(bounds).convert('RGB');array=np.asarray(crop)
            # Conservative central cheek/forehead patches, intersected with contour.
            mask=Image.new('L',crop.size,0);draw=ImageDraw.Draw(mask)
            contour=face['landmarks'].get('faceContour',[])
            if contour:draw.polygon([(px*crop.width,(1-py)*crop.height) for px,py in contour],fill=255)
            else:draw.rectangle((0,0,crop.width,crop.height),fill=255)
            patch=np.zeros(array.shape[:2],bool)
            for x0,y0,x1,y1 in ((.25,.10,.75,.22),(.16,.46,.36,.60),(.64,.46,.84,.60)):
                patch[int(y0*crop.height):int(y1*crop.height),int(x0*crop.width):int(x1*crop.width)]=True
            patch &= np.asarray(mask)>0
            patch &= array.mean(axis=2)>20
            if patch.sum()>=64:
                rgb=np.median(array[patch],axis=0);lab=lab_d65(rgb)
                row['face_region_rgb_median']=rgb.tolist();row['face_region_lab_d65']=lab.tolist()
                if previous_lab is not None:row['face_region_delta_e76']=float(np.linalg.norm(lab-previous_lab))
                previous_lab=lab
            else:row['color_status']='insufficient_region';previous_lab=None
            gray=np.asarray(crop.convert('L').resize((128,128),Image.Resampling.BILINEAR))
            row['normalized_face_laplacian_variance']=quality.sharpness(gray)
        for side in ('left','right'):
            eligible=(face['confidence']>=.8 and row.get(side+'_eye_open_ratio',0)>=.15)
            row[side+'_pupil_observation_eligible']=bool(eligible and side+'_pupil_relative_to_eye' in row)
        if previous is not None:row['motion_registered_change']=registered_change(previous,gray)
        previous=gray;row['status']='measured';rows.append(row)
    return rows


def summarize_features(rows):
    result={'frames':len(rows),'uncertain_frames':[r['frame'] for r in rows if r['status']!='measured']}
    for key in ('yaw_degrees','roll_degrees','center_step_over_face_width','center_acceleration_over_face_width',
                'face_region_delta_e76','normalized_face_laplacian_variance'):
        result[key]=quality.summarize([r[key] for r in rows if r.get(key) is not None])
    result['registered_luma_mae']=quality.summarize([r['motion_registered_change']['registered_luma_mae'] for r in rows
        if r.get('motion_registered_change',{}).get('status')=='measured'])
    for side in ('left','right'):
        eligible=side+'_pupil_observation_eligible';pupil=side+'_pupil_relative_to_eye'
        changes=[float(np.linalg.norm(np.asarray(b[pupil])-a[pupil])) for a,b in zip(rows,rows[1:])
          if a.get(eligible) and b.get(eligible) and b['frame']==a['frame']+1]
        result[side+'_eligible_pupil_adjacent_displacement']=quality.summarize(changes)
    result['pupil_eligible_frames']={side:sum(r.get(side+'_pupil_observation_eligible',False) for r in rows) for side in ('left','right')}
    return result


def graph(rows,keys,colors,title,width=700,height=150):
    data=[r[k] for r in rows for k in keys if isinstance(r.get(k),(int,float))]
    low=min(data,default=0);high=max(data,default=1)
    if high-low<.01:high=low+.01
    content=[f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}" class="timeline" data-width="{width}">',
        f'<title>{html.escape(title)}</title><text x="45" y="13">{html.escape(title)} ({low:.3f}…{high:.3f})</text>']
    for seconds in (0,3,6,8,10):
        x=45+seconds/10*(width-60)
        content.append(f'<path d="M{x} 20V{height-20}" stroke="#a88c3d"/><text x="{x}" y="{height-3}">{seconds}s</text>')
    for key,color in zip(keys,colors):
        commands=[];active=False
        for r in rows:
            value=r.get(key)
            if not isinstance(value,(int,float)):active=False;continue
            x=45+r['frame']/240*(width-60);y=25+(high-value)/(high-low)*(height-50)
            commands.append(('L' if active else 'M')+f'{x:.2f},{y:.2f}');active=True
        content.append(f'<path d="{" ".join(commands)}" stroke="{color}" fill="none" stroke-width="1.5"/>')
    content.append('</svg>');return ''.join(content)


def write_viewer(out,cases):
    body=['<!doctype html><html lang="de"><meta charset="utf-8"><title>LTX Gesichtsqualität</title>',
    '<style>body{background:#111722;color:#e7edf7;font:15px system-ui;margin:24px}a{color:#8cf}button,input{font:inherit}section{border:1px solid #526070;padding:12px;margin:14px 0}video{width:240px;max-height:440px}img{max-width:100%}.cases{display:flex;flex-wrap:wrap;gap:20px}.case{flex:1;min-width:280px;max-width:760px}svg{width:100%;background:#182132}svg text{fill:#ddd;font-size:11px}table{border-collapse:collapse}td,th{border:1px solid #556;padding:7px}pre{white-space:pre-wrap}.controls{position:sticky;top:0;background:#182132;padding:12px;z-index:1}.frame{max-height:600px}</style>',
    '<h1>LTX: synchroner Vergleich und native Gesichtsanalyse</h1>',
    '<p>Augenöffnung, Geometrie und Farbmessungen sind Detektorbeobachtungen. Mimik, Pose, Licht und Registrierungsfehler beeinflussen sie. Kein automatischer Identitäts- oder Qualitätsnachweis; kein Gesicht wird retuschiert.</p>',
    '<div class="controls"><button id="play">Alle abspielen</button> <button id="pause">Pause</button> <button id="back">−1 Frame</button> <button id="next">+1 Frame</button> <label>Zeit <input id="seek" type="range" min="0" max="240" value="0" step="1"></label> <output id="clock">0.000 s / Frame 0</output></div>',
    '<table><tr><th>Fall</th><th>Canvas / FPS / Frames</th><th>A/V Start-/Enddifferenz</th><th>Duplikate / PTS-Fehler</th><th>Generierung</th><th>unsichere Detektionen</th></tr>']
    for c in cases:
        v=c['video'];t=v['technical'];m=v['metrics'];s=c['summary']
        body.append(f'<tr><td>{html.escape(c["label"])}</td><td>{t["width"]}×{t["height"]} / {t["fps"]} / {t["frames"]}</td><td>{t["av_start_offset_seconds"]} / {t["av_end_offset_seconds"]}</td><td>{len(m["exact_duplicate_frames"])} / {len(t["pts_anomalies"])}</td><td>{(v.get("job") or {}).get("generation_seconds")}</td><td>{len(s["uncertain_frames"])}</td></tr>')
    body.append('</table><div class="cases">')
    for c in cases:
        label=c['label'];safe=html.escape(label);rows=c['features'];v=c['video']
        body.extend([f'<section class="case"><h2>{safe}</h2>',f'<video controls preload="metadata" src="{safe}/video.mp4"></video>',
          f'<p><img class="frame" data-label="{safe}" src="dense/{safe}/frame-000.png"></p>',
          graph(rows,['left_eye_open_ratio','right_eye_open_ratio'],['#66dcff','#ff9b77'],'Augenöffnung links / rechts, rollkorrigiert'),
          graph(rows,['yaw_degrees','eye_line_degrees'],['#77eaaa','#dbaaff'],'Pose: grober Vision-Yaw / Augenlinienwinkel, Grad'),
          graph(rows,['face_region_delta_e76'],['#ffa64a'],'Gesichtsregion: benachbarte Lab-D65-Farbänderung'),
          graph(rows,['center_step_over_face_width'],['#77eaaa'],'Bewegung des Gesichtsmittelpunkts / Gesichtsbreite'),
          '<details><summary>Originalfoto und native Gesichts-/Grenzframes</summary>'])
        if v.get('source_preview'):body.append(f'<img style="max-height:400px" src="{safe}/{v["source_preview"]}">')
        body.extend([f'<img src="{safe}/face-contact-sheet.jpg">','</details>',
          '<details><summary>Abschnitte, Lidschluss-Kandidaten und Messunsicherheit</summary><pre>'+html.escape(json.dumps({'segments':c['segments'],'complete_timeline':c['complete_timeline']},indent=2))+'</pre></details>',
          '<details><summary>Zusätzliche Messwerte und Settings</summary><pre>'+html.escape(json.dumps({'features':c['summary'],'settings':(v.get('job') or {}).get('settings')},indent=2))+'</pre></details></section>'])
    body.append('</div><p><a href="facial-report.json">Alle Messwerte und Methodik (JSON)</a></p>')
    body.append('''<script>
const videos=[...document.querySelectorAll('video')], frames=[...document.querySelectorAll('.frame')], slider=document.querySelector('#seek'), clock=document.querySelector('#clock');
let updating=false;const master=videos[0];
function show(t){const n=Math.max(0,Math.min(240,Math.round(t*24)));slider.value=n;clock.textContent=`${(n/24).toFixed(3)} s / Frame ${n}`;for(const im of frames){const path=`dense/${im.dataset.label}/frame-${String(n).padStart(3,'0')}.png`;if(im.getAttribute('src')!==path)im.src=path;}}
function seek(t){updating=true;for(const v of videos){v.pause();if(v.readyState>=1)v.currentTime=Math.min(t,v.duration-.001);}show(t);updating=false;}
slider.oninput=()=>seek(Number(slider.value)/24);document.querySelector('#back').onclick=()=>seek(Math.max(0,(Number(slider.value)-1)/24));document.querySelector('#next').onclick=()=>seek(Math.min(10,(Number(slider.value)+1)/24));
document.querySelector('#play').onclick=async()=>{const t=master.currentTime;for(const v of videos){v.muted=v!==master;if(v.readyState>=1&&Math.abs(v.currentTime-t)>.04)v.currentTime=t;await v.play().catch(()=>{});}};
document.querySelector('#pause').onclick=()=>{for(const v of videos)v.pause();};
for(const svg of document.querySelectorAll('svg.timeline'))svg.onclick=e=>{const box=svg.getBoundingClientRect();seek(Math.max(0,Math.min(10,((e.clientX-box.left)/box.width*700-45)/640*10)));};
master.addEventListener('seeking',()=>{if(updating)return;for(const v of videos.slice(1))if(v.readyState>=1&&Math.abs(v.currentTime-master.currentTime)>.08)v.currentTime=master.currentTime;show(master.currentTime);});
function tick(){if(!master.paused){for(const v of videos.slice(1))if(v.readyState>=1&&Math.abs(v.currentTime-master.currentTime)>.08)v.currentTime=master.currentTime;show(master.currentTime);}requestAnimationFrame(tick);}tick();
</script></html>''')
    (out/'index.html').write_text('\n'.join(body))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('videos',nargs='+');p.add_argument('--job',action='append',default=[])
    p.add_argument('--out',type=Path,required=True);p.add_argument('--vision-helper',type=Path,required=True);p.add_argument('--reuse',action='store_true',help='Reuse only SHA-verified existing measurements')
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True);jobs=dict(x.split('=',1) for x in args.job);cases=[]
    (args.out/'dense').mkdir(exist_ok=True)
    for arg in args.videos:
        label,path=arg.split('=',1);video=Path(path)
        if not re.fullmatch('[A-Za-z0-9_-]+',label):p.error('Invalid case label')
        cache=args.out/(label+'-case.json')
        job=Path(jobs[label]) if label in jobs else None
        source=json.loads(job.read_text()).get('payload',{}).get('first_frame') if job else None
        provenance={'video_sha256':quality.sha256(video), 'job_sha256':quality.sha256(job) if job else None,
          'source_sha256':quality.sha256(Path(source)) if source and Path(source).is_file() else None,
          'vision_helper_sha256':quality.sha256(args.vision_helper),
          'scripts':{name:quality.sha256(Path(__file__).with_name(name)) for name in
            ('benchmark-ltx-facial-quality.py','benchmark-video-quality.py','analyze-ltx-face-segments.py')}}
        if args.reuse and cache.exists():
            case=json.loads(cache.read_text())
            if case.get('provenance')!=provenance:raise ValueError('Cached inputs or analysis changed; use a fresh output directory')
            if not (args.out/'dense'/label/'frame-240.png').is_file():raise ValueError('Cached native frames missing')
            cases.append(case);continue
        result=quality.benchmark(label,video,args.out,jobs.get(label),args.vision_helper)
        dense=segments.analyze(label,video,args.out/'dense',args.vision_helper,{'videos':[result]})
        geometry=json.loads((args.out/'dense'/label/'native-landmarks.json').read_text())
        features=face_features(args.out/'dense'/label,geometry)
        timeline=segments.segment_summary(features,0,241)
        for candidate in timeline.get('bilateral_low_aperture_candidates',[]):
            next_frame=candidate['last_frame']+1
            candidate['reopening_frame']=next_frame if next_frame<len(features) and features[next_frame]['status']=='measured' else None
            candidate['reopening_status']='above_candidate_threshold' if candidate['reopening_frame'] is not None else 'not_observed'
        case={'complete_timeline':timeline,'label':label,'provenance':provenance,'video':result,'segments':dense['segments'],'features':features,'summary':summarize_features(features)}
        cache.write_text(json.dumps(case,indent=2,allow_nan=False)+'\n');cases.append(case);print(label,'complete',flush=True)
    report={'schema_version':1,'environment':{'python':platform.python_version(), 'numpy':np.__version__,
      'ffmpeg':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]},'cases':cases,'methodology':{'landmarks':'Apple Vision CPU, every native frame; one face and confidence >=0.8 required. Vision yaw/roll are coarse quantized estimates, not continuous pose truth. Eye-line angle is continuous detector geometry.',
      'eyes':'Pupil changes only between adjacent eligible open-eye/confident frames, normalized by eye width/height; not iris segmentation. Roll-corrected aperture. Low-aperture candidates retain the existing 45%-of-segment-p90 heuristic, not a medical/identity verdict.',
      'color':'Median approximate forehead/cheek face patches intersected with contour, uncalibrated sRGB -> Lab D65, adjacent Delta E76. Not validated skin segmentation.',
      'motion':'Face box center step/acceleration; 128x128 normalized luma translation phase correlation within 8 pixels, not optical flow or an identity metric.',
      'limits':'Expression, pose, lighting and detector jitter confound all perceptual proxies. No automatic acceptance. A/V offsets are stream timing, not lip sync.'}}
    (args.out/'facial-report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');write_viewer(args.out,cases);print(args.out/'index.html')


if __name__=='__main__':main()
