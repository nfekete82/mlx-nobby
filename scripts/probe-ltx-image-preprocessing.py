#!/usr/bin/env python3
"""Execute pinned NumPy/Pillow/FFmpeg preprocessing definitions on CPU only.

AST extraction deliberately omits native MLX imports and tensor/VAE functions.
It measures pixel preprocessing, not VAE reconstruction or generation quality.
"""
import argparse
import ast
from io import BytesIO
import json
import logging
import math
from pathlib import Path
import shutil
import subprocess
import importlib.util

import numpy as np
from PIL import Image,ImageCms,UnidentifiedImageError

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('quality',Path(__file__).with_name('benchmark-video-quality.py'))
quality=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(quality)
FUNCTIONS={'decode_image','encode_single_frame','decode_single_frame','_parse_size_from_stderr',
           'preprocess','_bilinear_resize_axis','resize_and_center_crop'}
EXPECTED_HEAD='b82b97e3d000e01361f8cfcb745244b15b89a521'


def cpu_native_functions(runtime):
    head=subprocess.check_output(['git','-C',str(runtime),'rev-parse','HEAD'],text=True).strip()
    if head!=EXPECTED_HEAD:raise ValueError('Unexpected native runtime commit')
    source=runtime/'packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/utils/media_io.py'
    tree=ast.parse(source.read_text())
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in FUNCTIONS]
    if {n.name for n in selected}!=FUNCTIONS:raise ValueError('Native preprocessing contract missing')
    namespace={'np':np,'BytesIO':BytesIO,'Image':Image,'ImageCms':ImageCms,
        'UnidentifiedImageError':UnidentifiedImageError,'Path':Path,'subprocess':subprocess,
        'math':math,'find_ffmpeg':lambda:shutil.which('ffmpeg'),
        '_ORIENTATION_EXIF_KEY':274,'_ORIENTATION_TO_ROTATION':{3:180,6:270,8:90},
        '_SRGB_PROFILE':ImageCms.createProfile('sRGB'),'logger':logging.getLogger('ltx.cpu.probe')}
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    module=ast.fix_missing_locations(ast.Module(body=[future,*selected],type_ignores=[]))
    exec(compile(module,str(source),'exec'),namespace)
    return namespace,quality.sha256(source)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True)
    funcs,source_hash=cpu_native_functions(args.runtime)
    prepared=args.out/'prepared.png'
    # Exact existing contain preparation; no import of inference/provider modules.
    subprocess.run(['ffmpeg','-v','error','-i',str(args.source),'-vf',
        'scale=704:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=704:1280:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1',
        '-frames:v','1',str(prepared)],check=True)
    decoded=funcs['decode_image'](str(prepared))
    records=[]
    for crf in (18,0):
        compressed=funcs['preprocess'](decoded,crf)
        Image.fromarray(compressed).save(args.out/f'input-crf-{crf}.png')
        records.append({'crf':crf,'source_rgb_mae':float(np.abs(decoded.astype(float)-compressed).mean())})
        for name,h,w in [('half',640,352),('full',1280,704)]:
            result=funcs['resize_and_center_crop'](compressed,h,w)
            target=args.out/f'{name}-crf-{crf}.png'
            Image.fromarray(np.clip(np.round(result),0,255).astype(np.uint8)).save(target)
    metrics={}
    for name in ('half','full'):
        a=np.asarray(Image.open(args.out/f'{name}-crf-0.png').convert('L'))
        b=np.asarray(Image.open(args.out/f'{name}-crf-18.png').convert('L'))
        metrics[name]={'crf18_vs_no_recompression_ssim':quality.ssim(a,b),
            'luma_mae':float(np.abs(a.astype(float)-b).mean()),
            'crf0_laplacian_variance':quality.sharpness(a),'crf18_laplacian_variance':quality.sharpness(b)}
    result={'runtime':EXPECTED_HEAD,'native_media_io_sha256':source_hash,'source_sha256':quality.sha256(args.source),
        'prepared_size':[704,1280],'pixel_roundtrip':records,'stages':metrics,
        'limits':'CPU pixels only; no MLX module import, tensor, model or VAE execution. Lower pixel error does not prove better generated faces; CRF 18 is the model training-aligned default.'}
    (args.out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
