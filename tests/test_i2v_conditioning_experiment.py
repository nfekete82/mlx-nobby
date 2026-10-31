"""CPU-only opt-in contract, worker payload and checkpoint compatibility."""
from dataclasses import dataclass
from pathlib import Path
import threading
from unittest import mock

import pytest
import video_service as service
import video_rolling as rolling
import video_providers_mlx as provider
from video_mlx_compat import initial_image_inputs


@dataclass
class NativeImage:
    path: str
    frame_idx: int
    strength: float
    crf: int | None

    @classmethod
    def replace(cls,path,frame_idx,strength,crf=None):
        return cls(path,frame_idx,strength,crf)


def test_default_single_image_shorthand_is_unchanged():
    image,anchors=initial_image_inputs('prepared.png',[],None,NativeImage)
    assert image=='prepared.png' and anchors==[]


def test_opt_in_is_one_frame_zero_replacement_and_native_crf_only():
    image,anchors=initial_image_inputs('prepared.png',[],0,NativeImage)
    assert image is None
    assert anchors==[NativeImage('prepared.png',0,1.0,0)]
    for image,anchors,crf in [('x',[],18),('x',[],False),(None,[],0),('x',[{}],0)]:
        with pytest.raises(ValueError):initial_image_inputs(image,anchors,crf,NativeImage)
    with pytest.raises(ValueError):initial_image_inputs('x',[],0,object)


def request(**extra):
    return service.JobCreate(operation='i2v',chat_id='test',chat_revision=0,payload={
        'prompt':'Natural subtle movement','first_frame':'/managed/portrait.png',
        'continuation_mode':'rolling','duration':10,'quality':'standard','aspect_ratio':'9:16',**extra})


@pytest.fixture
def photo(monkeypatch):
    monkeypatch.setattr(service,'validate_first_frame',lambda _:Path('/managed/portrait.png'))
    monkeypatch.setattr(service,'i2v_source_size',lambda _:(704,1280))


def test_api_only_accepts_explicit_zero_for_single_rolling_i2v(photo):
    assert request().payload.i2v_image_crf is None
    assert request(i2v_image_crf=0).payload.i2v_image_crf==0
    for value in (18,1,False,'0',0.0,-1):
        with pytest.raises(ValueError):request(i2v_image_crf=value)
    with pytest.raises(ValueError):request(i2v_image_crf=0,continuation_mode='segmented')
    with pytest.raises(ValueError):service.JobCreate(operation='t2v',chat_id='x',chat_revision=0,payload={
        'prompt':'Natural movement','duration':10,'continuation_mode':'rolling','i2v_image_crf':0})


def test_default_checkpoint_fingerprint_unchanged_but_opt_in_is_distinct(tmp_path,monkeypatch):
    (tmp_path/'embedded_config.json').write_text('{}')
    monkeypatch.setattr(rolling.video_registry,'model_path',lambda _:tmp_path)
    params={'prompt':'Natural motion','duration':10,'resolution':'720p','fps':24,'first_frame':None}
    model={'id':'test'};plan=rolling.plan(10,'720p')
    base=rolling._fingerprint(model,params,plan,'pinned')
    assert rolling._fingerprint(model,dict(params,i2v_image_crf=None),plan,'pinned')==base
    assert rolling._fingerprint(model,dict(params,i2v_image_crf=0),plan,'pinned')!=base


def test_old_default_job_payload_remains_eligible_for_resume(photo,monkeypatch):
    old=request().payload.model_dump(exclude={'resume_from','i2v_image_crf'})
    previous={'id':'a'*24,'chat_id':'test','status':'failed','payload':old,'long_plan':{'strategy':rolling.STRATEGY}}
    monkeypatch.setattr(service,'_jobs',{'a'*24:previous})
    monkeypatch.setattr(service,'preflight_profile',lambda *a:None)
    monkeypatch.setattr(service.video_long,'runtime_version',lambda:'pinned')
    assert service.preflight(request(resume_from='a'*24))['available']
    with pytest.raises(service.HTTPException):
        service.preflight(request(resume_from='a'*24,i2v_image_crf=0))


def test_cli_rejects_experiment_instead_of_inventing_a_flag():
    with pytest.raises(ValueError,match='native worker'):
        provider._command({}, {'i2v_image_crf':0},Path('/tmp/never-generated.mp4'))


def test_provider_rejects_unpinned_or_nonworker_experiment_before_loading(monkeypatch,tmp_path):
    params={'first_frame':'/managed/image.png','i2v_image_crf':0,'continuation_mode':'rolling'}
    monkeypatch.setattr(provider,'PERSISTENT_WORKER',False)
    with mock.patch.object(provider,'availability') as availability:
        with pytest.raises(ValueError):provider.generate({},params,tmp_path/'never.mp4',cancel_event=threading.Event())
    availability.assert_not_called()
    monkeypatch.setattr(provider,'PERSISTENT_WORKER',True)
    monkeypatch.setattr(service.video_long,'runtime_version',lambda:'pinned')
    monkeypatch.setattr(provider,'LTX_MLX_RUNTIME_ROOT',tmp_path)
    with pytest.raises(ValueError,match='exact pinned'):
        provider.generate({},params,tmp_path/'never.mp4',cancel_event=threading.Event())


def test_warm_worker_forwards_only_explicit_crf(monkeypatch):
    runtime=mock.Mock();runtime.health.return_value={}
    runtime_reused=[];sent=[]
    monkeypatch.setattr(provider,'_acquire_runtime',lambda *a:(runtime,False))
    def rpc(method,path,payload=None,*args):
        sent.append(payload)
        return {'ok':True}
    monkeypatch.setattr(provider,'_json_request',rpc)
    params={'prompt':'Natural motion','width':704,'height':1280,'frames':145,'fps':24,'seed':0}
    for crf in (None,0):
        provider._run_warm_worker({},dict(params,i2v_image_crf=crf),Path('/tmp/output.mp4'),
            image=Path('/tmp/prepared.png'),cancel_event=threading.Event())
    assert 'i2v_image_crf' not in sent[0]
    assert sent[1]['i2v_image_crf']==0
    assert sent[1]['images']==[]


def test_real_worker_function_sends_one_explicit_anchor_to_pipeline(tmp_path,monkeypatch):
    import ast
    import sys
    import time
    import types
    from video_mlx_compat import initial_image_inputs
    args_module=types.ModuleType('ltx_pipelines_mlx.utils.args')
    args_module.ImageConditioningInput=NativeImage
    monkeypatch.setitem(sys.modules,'ltx_pipelines_mlx.utils.args',args_module)
    recorded=[]
    class Pipe:
        _pending_loras=[]
        def generate_and_save(self,**options):
            recorded.append(options)
            Path(options['output_path']).write_bytes(b'CPU fixture only')
    pipe=Pipe()
    tree=ast.parse(Path('video_mlx_worker.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate')
    namespace={'time':time,'Path':Path,'_PIPELINE':pipe,'_GENERATION_LOCK':threading.Lock(),
        '_STATE_LOCK':threading.RLock(),'_STATE':{'generation_count':0},'_pipeline':lambda:pipe,
        'request_loras':lambda _:[],'prepare_uncensored_loras':lambda _:None,
        '_install_progress_hook':lambda *a:None,'initial_image_inputs':initial_image_inputs}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'real-worker-function','exec'),namespace)
    payload={'prompt':'Natural movement','output':str(tmp_path/'fixture.mp4'),'width':704,
        'height':1280,'frames':145,'fps':24,'seed':0,'stage1_steps':8,'stage2_steps':3,
        'image':'prepared.png','images':[],'i2v_image_crf':0}
    result=namespace['_generate'](payload)
    assert result['ok']
    assert recorded[0]['image'] is None
    assert recorded[0]['images']==[NativeImage('prepared.png',0,1.0,0)]
    assert recorded[0]['stage1_steps']==8 and recorded[0]['stage2_steps']==3
