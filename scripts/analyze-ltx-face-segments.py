#!/usr/bin/env python3
"""Dense CPU-only rolling diagnostics at matched frame indices, never generation.

Requires existing benchmark dependencies and an optional Apple Vision CPU helper.
Geometry is a detector observation, not a facial identity or blink-quality verdict.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw

SPEC=importlib.util.spec_from_file_location('video_quality',Path(__file__).with_name('benchmark-video-quality.py'))
quality=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)
SEGMENTS=((0,145),(145,193),(193,241))


def eye_observations(face):
    points=face['landmarks']
    w,h=face['bounding_box'][2:]
    pixel=lambda name: np.asarray(points[name],dtype=float)*[w,h]
    if not points.get('leftEye') or not points.get('rightEye'):
        return {}
    left,right=pixel('leftEye'),pixel('rightEye')
    direction=right.mean(0)-left.mean(0)
    distance=np.linalg.norm(direction)
    if distance<1e-8:return {}
    u=direction/distance
    v=np.array([-u[1],u[0]])
    result={'interocular_over_box_width':float(distance/w),'eye_line_degrees':float(np.degrees(np.arctan2(u[1],u[0])))}
    for name,eye in [('left',left),('right',right)]:
        local=np.column_stack((eye@u,eye@v))
        width=np.ptp(local[:,0]);height=np.ptp(local[:,1])
        result[name+'_eye_open_ratio']=float(height/max(1e-8,width))
        pupil=name+'Pupil'
        if points.get(pupil):
            offset=pixel(pupil).mean(0)-eye.mean(0)
            result[name+'_pupil_relative_to_eye']=[float(offset@u/max(1e-8,width)),float(offset@v/max(1e-8,height))]
    nose=pixel('nose') if points.get('nose') else None
    if nose is not None:result['nose_to_eye_mid_over_interocular']=float(np.linalg.norm(nose.mean(0)-(left.mean(0)+right.mean(0))/2)/distance)
    if points.get('outerLips'):
        lips=pixel('outerLips')
        result['mouth_width_over_interocular']=float(np.ptp(lips@u)/distance)
    return result


def segment_summary(rows,start,end):
    selected=[r for r in rows if start<=r['frame']<end]
    result={'first_frame':start,'last_frame':end-1,'frames':len(selected),
        'face_count_histogram':{str(n):sum(r['face_count']==n for r in selected) for n in sorted({r['face_count'] for r in selected})}}
    for key in ('left_eye_open_ratio','right_eye_open_ratio','interocular_over_box_width',
                'nose_to_eye_mid_over_interocular','mouth_width_over_interocular'):
        values=[r[key] for r in selected if key in r]
        result[key]=quality.summarize(values)
        deltas=[abs(b[key]-a[key]) for a,b in zip(selected,selected[1:]) if key in a and key in b]
        result[key+'_adjacent_absolute_change']=quality.summarize(deltas)
    # Report candidate closures, not an asserted blink count. Turning, squinting,
    # illumination and landmark noise can all satisfy this heuristic.
    good=[r for r in selected if all(k in r for k in ('left_eye_open_ratio','right_eye_open_ratio'))]
    if good:
        l=np.percentile([r['left_eye_open_ratio'] for r in good],90)
        r=np.percentile([r['right_eye_open_ratio'] for r in good],90)
        low=[x['frame'] for x in good if x['left_eye_open_ratio']<.45*l and x['right_eye_open_ratio']<.45*r]
        groups=[]
        for frame in low:
            if not groups or frame>groups[-1][-1]+1:groups.append([])
            groups[-1].append(frame)
        result['bilateral_low_aperture_candidates']=[{'first_frame':g[0],'last_frame':g[-1],'frames':len(g),'duration_seconds':len(g)/24} for g in groups]
        result['aperture_reference_p90']={'left':float(l),'right':float(r)}
    return result


def diagnostic_sheets(directory,rows,prefix):
    by_frame={r['frame']:r for r in rows}
    for segment,(start,end) in enumerate(SEGMENTS):
        # Fixed 6-frame stride plus exact segment endpoints; no cherry-picking.
        indices=sorted(set(range(start,end,6))|{start,end-1})
        columns=8;cell_w,cell_h=200,230
        canvas=Image.new('RGB',(columns*cell_w,((len(indices)+columns-1)//columns)*cell_h),'#171a22')
        draw=ImageDraw.Draw(canvas)
        for i,index in enumerate(indices):
            row=by_frame[index]
            source=directory/row.get('face_crop',row['image'])
            with Image.open(source) as im:
                im.thumbnail((cell_w,200))
                x=(i%columns)*cell_w;y=(i//columns)*cell_h
                canvas.paste(im,(x+(cell_w-im.width)//2,y))
            draw.text((x+3,y+204),f'n={index}  t={index/24:.3f}s',fill='white')
            if 'left_eye_open_ratio' in row:
                draw.text((x+3,y+216),f"eye {row['left_eye_open_ratio']:.2f}/{row['right_eye_open_ratio']:.2f}",fill='white')
        canvas.save(directory/f'{prefix}-segment-{segment+1}.jpg',quality=96)


def analyze(label,video,out,helper,cached):
    directory=out/label;directory.mkdir()
    info=quality.probe(video)
    if info['frames']!=241 or info['fps']!=24:
        raise ValueError('This diagnostic requires the 241-frame/24-FPS rolling layout')
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-fps_mode','passthrough','-start_number','0',str(directory/'frame-%03d.png')],check=True,timeout=180)
    frames=[{'frame':i,'time':info['pts'][i],'relative_time':info['pts'][i]-info['pts'][0],'image':f'frame-{i:03}.png'} for i in range(241)]
    geometry=quality.face_geometry(helper,directory,frames)
    if geometry['status']!='measured':raise RuntimeError('CPU landmarks unavailable: '+str(geometry))
    rows=[]
    for sample in geometry['samples']:
        row={k:v for k,v in sample.items() if k!='faces'}
        if sample['face_count']==1:row.update(eye_observations(sample['faces'][0]))
        rows.append(row)
    diagnostic_sheets(directory,rows,'face')
    summaries=[segment_summary(rows,*bounds) for bounds in SEGMENTS]
    previous=next(v for v in cached['videos'] if v['label']==label)
    if quality.sha256(video)!=previous['sha256']:raise ValueError('Cached benchmark belongs to another video')
    for summary,(start,end) in zip(summaries,SEGMENTS):
        metrics=previous['metrics']['per_frame'][start:end]
        # Exclude the incoming join from within-segment change statistics.
        summary['within_segment_adjacent_ssim']=quality.summarize([r['adjacent_ssim'] for r in metrics[1:]])
        summary['within_segment_laplacian_variance']=quality.summarize([r['laplacian_variance'] for r in metrics])
    result={'label':label,'video_sha256':previous['sha256'],'segments':summaries,'per_frame':rows,
        'geometry_limits':'Rotation-normalized eye aperture and pupil estimates are noisy detector observations, not identity/blink diagnoses. Source pose, squinting and expression confound ratios.',
        'landmark_backend':geometry['backend']}
    (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    (directory/'native-landmarks.json').write_text(json.dumps(geometry,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('videos',nargs='+',help='before=/absolute/video.mp4 after=/absolute/video.mp4')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--vision-helper',type=Path,required=True)
    p.add_argument('--benchmark',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    cached=json.loads(args.benchmark.read_text())
    results=[]
    for arg in args.videos:
        label,path=arg.split('=',1)
        if label not in {'before','after'}:p.error('Expected before/after labels')
        results.append(analyze(label,Path(path),args.out,args.vision_helper,cached))
        print(label,'dense CPU analysis complete',flush=True)
    summary={'videos':[{k:v for k,v in r.items() if k!='per_frame'} for r in results],
             'phase':'Existing media only; no GPU inference or runtime modification.'}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
