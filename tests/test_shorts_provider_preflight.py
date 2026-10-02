from copy import deepcopy
from unittest.mock import Mock

import pytest

from agent import shorts_jobs, shorts_drafts, shorts_consistency_runtime as runtime, shorts_studio
from agent.shorts_planner import ShortProject
from agent.shorts_preflight import preflight_project


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs,'SHORTS_DIRECTORY',tmp_path/'shorts')
    monkeypatch.setattr(shorts_jobs,'SHORTS_JOBS_FILE',tmp_path/'shorts/jobs.json')
    monkeypatch.setattr(shorts_jobs,'MUSIC_DIRECTORY',tmp_path/'music')
    monkeypatch.setattr(shorts_jobs,'start_short_job',Mock())
    runtime._EDIT_CAPABILITY.update(checked_at=0.,available=False)
    return tmp_path


def project():
    return ShortProject.model_validate({'schema_version':2,'title':'Office','duration':10,
        'voice_enabled':False,'music_enabled':False,'consistency_mode':True,
        'scenes':[{'id':f'scene-{i}','duration':5,'video_prompt':'Office'} for i in range(2)]})


def models(edit=False, generate=True):
    return {'models':[{'id':'generator','provider':'mflux','enabled':True,'available':generate,'capabilities':['text_to_image']},
                      {'id':'edit','provider':'mflux','enabled':True,'available':edit,'capabilities':['image_edit']}]}


def test_incompatible_edit_warns_and_no_generator_blocks_before_job_creation(store, monkeypatch):
    from agent import image_api
    monkeypatch.setattr(image_api,'request',Mock(return_value=models()))
    p=project()
    assert preflight_project(p)['warnings']==['character_anchor_fallback']
    draft=shorts_drafts.save_draft(p.model_dump())
    monkeypatch.setattr(image_api,'request',Mock(return_value=models(generate=False)))
    with pytest.raises(ValueError,match='Keyframe-Generator'):
        shorts_drafts.render_draft(draft['id'])
    assert not shorts_jobs._load_jobs()
    shorts_jobs.start_short_job.assert_not_called()


def test_runtime_fallback_uses_t2i_and_structured_failure_has_scene_provider(store, monkeypatch):
    job=shorts_jobs.create_short_job(project(),chat_id='test')
    operations=[]
    def image(method,path,payload=None,timeout=15):
        if path=='/models': return models()
        if method=='POST': operations.append(payload['operation']);return {'id':'a'*24}
        return {'status':'failed','error':'unrecognized arguments: --required', 'model':'generator', 'provider':'mflux',
                'error_code':'IMAGE_PROVIDER_INCOMPATIBLE','error_detail_safe':'Missing --required'}
    monkeypatch.setattr(runtime,'_image_request',image)
    result=runtime.run_consistent_short_job(job['id'],poll_interval=0)
    assert operations==['generate']
    assert result['warnings']==['character_anchor_fallback']
    assert result['error_stage']=='keyframe' and result['error_scene_number']==1
    assert result['error_scene_id']=='scene-0' and result['error_provider']=='mflux'
    assert result['error_model']=='generator' and result['error_code']=='IMAGE_PROVIDER_INCOMPATIBLE'


def test_later_scene_incompatible_edit_falls_back_once_to_visual_bible(store, monkeypatch):
    job=shorts_jobs.create_short_job(project(),chat_id='test')
    shorts_jobs._update_job(job['id'],current_scene=1,
        scene_results=[{'scene_id':'scene-0','status':'completed','path':'scene0.mp4'}],
        keyframe_results=[{'scene_id':'scene-0','status':'completed','path':'scene0.png','image_id':'anchor'}])
    operations=[]
    def image(method,path,payload=None,timeout=15):
        if path=='/models':return models(edit=True)
        if method=='POST':operations.append(payload['operation']);return {'id':'a'*24}
        if operations[-1]=='edit':return {'status':'failed','error_code':'IMAGE_PROVIDER_INCOMPATIBLE','error':'incompatible'}
        return {'status':'completed','result':{'path':'scene1.png','id':'newframe'}}
    def video(method,path,payload=None,timeout=15):
        if method=='POST':return {'id':'b'*24}
        return {'status':'completed','result':{'path':'scene1.mp4'}}
    monkeypatch.setattr(runtime,'_image_request',image)
    monkeypatch.setattr(runtime,'_ORIGINAL_RUN_SHORT_JOB',lambda jid,**_:shorts_jobs._update_job(jid,status='completed'))
    result=runtime.run_consistent_short_job(job['id'],request_fn=video,poll_interval=0)
    assert operations==['edit','generate']
    assert result['status']=='completed' and len(result['scene_results'])==2
    assert 'character_anchor_fallback' in result['warnings']


def test_retry_creates_revision_and_reuses_existing_completed_scene(store, monkeypatch):
    from agent import image_api
    monkeypatch.setattr(image_api,'request',Mock(return_value=models()))
    frame=store/'frame.png';frame.write_bytes(b'image-fixture');video=store/'video.mp4';video.write_bytes(b'video-fixture')
    job=shorts_jobs.create_short_job(project(),chat_id='test')
    original=shorts_jobs._update_job(job['id'],current_scene=1,status='failed',phase='failed',
        scene_results=[{'scene_id':'scene-0','status':'completed','path':str(video)}],
        keyframe_results=[{'scene_id':'scene-0','status':'completed','path':str(frame)}],error='failed in scene 2')
    revision=shorts_studio.retry_short_job(job['id'])
    assert revision['id']!=job['id'] and revision['parent_job_id']==job['id']
    assert revision['current_scene']==1 and revision['scene_results']==original['scene_results']
    assert revision['keyframe_results']==original['keyframe_results']
    assert shorts_jobs.get_short_job(job['id'])==original
    shorts_jobs.start_short_job.assert_called_once_with(revision['id'])


def test_cancel_also_cancels_active_keyframe_child(store, monkeypatch):
    from agent import image_api
    calls=[]
    monkeypatch.setattr(image_api,'request',lambda *args,**kwargs:calls.append(args))
    job=shorts_jobs.create_short_job(project(),chat_id='test')
    shorts_jobs._update_job(job['id'],status='running',phase='keyframe',active_image_job_id='a'*24)
    cancelled=shorts_jobs.cancel_short_job(job['id'],request_fn=Mock())
    assert cancelled['status']=='cancelled' and cancelled['active_image_job_id'] is None
    assert calls==[('POST','/jobs/'+'a'*24+'/cancel',{})]
