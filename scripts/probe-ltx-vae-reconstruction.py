#!/usr/bin/env python3
"""Opt-in one-frame VAE reconstruction diagnostic; never changes video defaults.

Controller uses the normal exclusive video lease, model admission, managed
process ownership and two-second memory watchdog. Worker imports the pinned
native API only after admission. No transformer, text/audio encoder or downloads.
Run each spatial stage separately; a PNG round trip is not a temporal/blink test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
PIN='b82b97e3d000e01361f8cfcb745244b15b89a521'


def sha256(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def validate(runtime,model,stage):
    if stage not in {'half','full'}:raise ValueError('Expected half/full spatial stage')
    head=subprocess.check_output(['git','-C',str(runtime),'rev-parse','HEAD'],text=True).strip()
    dirty=subprocess.check_output(['git','-C',str(runtime),'status','--porcelain','--untracked-files=no'],text=True).strip()
    if head!=PIN or dirty:raise ValueError('Requires the unchanged pinned 0.18 runtime')
    files={name:sha256(model/name) for name in ('vae_encoder_conv.safetensors','vae_decoder_conv.safetensors','embedded_config.json')}
    return {'runtime_commit':head,'checkpoint_sha256':files,'model_repository':'dgrauet/ltx-2.5-mlx-q4'}


def worker(args):
    # Packages are installed in the pinned runtime venv. Never modify sys.path
    # to substitute a native implementation, nor resolve a remote model ID.
    import mlx.core as mx
    import numpy as np
    from PIL import Image
    from ltx_pipelines_mlx.utils.blocks import ImageConditioner,VideoDecoder
    from ltx_pipelines_mlx.utils.media_io import load_image_and_preprocess
    from ltx_core_mlx.utils.memory import aggressive_cleanup
    width,height=(352,640) if args.stage=='half' else (704,1280)
    conditioner=ImageConditioner(args.model)
    crf=conditioner.default_image_crf
    if crf!=18:raise ValueError('Unexpected checkpoint conditioning CRF')
    started=time.monotonic()
    pixels=load_image_and_preprocess(args.image,height,width,crf=crf)
    # Persist exactly the tensor sent to the VAE, not the uncompressed source.
    rgb=np.asarray(mx.clip((pixels[0].transpose(1,2,0).astype(mx.float32)+1)*127.5,0,255)).astype(np.uint8)
    Image.fromarray(rgb).save(args.out/'input.png')
    encoder=conditioner.load()
    latent=encoder.encode(pixels[:,:,None,:,:]);mx.eval(latent)
    latent_shape=list(latent.shape);latent_dtype=str(latent.dtype)
    del encoder,pixels;conditioner.free();aggressive_cleanup()
    encoder_seconds=time.monotonic()-started
    decoder_block=VideoDecoder(args.model,verbose=True,video_decoder='conv')
    decoder=decoder_block.load();decoded=decoder.decode(latent);mx.eval(decoded)
    decoded_shape=list(decoded.shape)
    rgb_out=np.asarray(mx.clip((decoded[0,:,0].transpose(1,2,0).astype(mx.float32)+1)*127.5,0,255)).astype(np.uint8)
    Image.fromarray(rgb_out).save(args.out/'reconstruction.png')
    metadata={'stage':args.stage,'width':width,'height':height,'frames':1,'image_crf':crf,
      'latent_shape':latent_shape,'latent_dtype':latent_dtype,'decoded_shape':decoded_shape,
      'encoder_load_and_encode_seconds':encoder_seconds,'total_worker_seconds':time.monotonic()-started,
      'metal_peak_gib':mx.get_peak_memory()/2**30,'rgb_mae':float(np.abs(rgb_out.astype(float)-rgb).mean()),
      'scope':'One-frame conv-VAE reconstruction only; no denoising, audio, output codec or temporal/blink inference.'}
    del decoder,decoded,latent;decoder_block.free();aggressive_cleanup()
    (args.out/'reconstruction.json').write_text(json.dumps(metadata,indent=2)+'\n')


def controller(args):
    sys.path.insert(0,str(ROOT))
    import ai_lifecycle_gate as gate
    import managed_process
    import runtime_coordinator as coordinator
    from video_providers import _prepare_first_frame
    provenance=validate(args.runtime,args.model,args.stage)
    if not args.image.is_file():raise ValueError('Local source image missing')
    for index,url in enumerate(('http://127.0.0.1:8060/health','http://127.0.0.1:8010/api/system/job-queue')):
        with urllib.request.urlopen(url,timeout=10) as response:state=json.load(response)
        if index==0 and (state.get('ok') is not True or state.get('status')!='ready'):
            raise RuntimeError('Video health is not ready; diagnostic was not started')
        if index==1 and not all(isinstance(state.get(key),int) for key in ('active_count','waiting_count')):
            raise RuntimeError('Unknown Agent queue state; diagnostic was not started')
        if state.get('active_job_id') or state.get('active_count',0) or state.get('waiting_count',0) or state.get('runtime',{}).get('active'):
            raise RuntimeError('Video/Agent busy; diagnostic was not started')
    args.out.mkdir(parents=True,exist_ok=False)
    provenance.update({'source_sha256':sha256(args.image),'stage':args.stage,'started_at':time.time(),
      'resize':_prepare_first_frame(args.image,704,1280,'contain',args.out/'prepared.png')})
    gate.check();cancel=threading.Event()
    with coordinator.video_runtime(cancel,chat_loaded=coordinator._default_chat_loaded,
       chat_command=coordinator._default_chat_command,exclusive_models=True) as admission:
        provenance['admission']=admission
        (args.out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
        command=[str(args.runtime/'.venv/bin/python'),str(Path(__file__).resolve()),'--worker',
          '--image',str((args.out/'prepared.png').resolve()),'--model',str(args.model.resolve()),
          '--runtime',str(args.runtime.resolve()),'--stage',args.stage,'--out',str(args.out.resolve())]
        process=None;started=time.monotonic()
        try:
            with (args.out/'worker.log').open('w') as log,(args.out/'memory.jsonl').open('w') as memory:
                process=managed_process.spawn(command,owner='video:vae-diagnostic',cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                while process.poll() is None:
                    snapshot=coordinator.memory_budget_snapshot()
                    memory.write(json.dumps({'timestamp':time.time(),'memory':snapshot})+'\n');memory.flush()
                    coordinator.ensure_active_memory_safe(snapshot,baseline_swap_gb=admission['memory_admission']['swap_used_gb'])
                    gate.check()
                    if time.monotonic()-started>180:raise TimeoutError('VAE diagnostic deadline exceeded; no retry')
                    time.sleep(2)
                if process.returncode:raise RuntimeError(f'Native diagnostic exited {process.returncode}; inspect worker.log, no retry')
                managed_process.forget(process)
        finally:
            if process is not None:managed_process.terminate(process)
    print(args.out/'reconstruction.json',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--stage',choices=['half','full'],required=True)
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.worker:worker(args)
    else:controller(args)


if __name__=='__main__':main()
