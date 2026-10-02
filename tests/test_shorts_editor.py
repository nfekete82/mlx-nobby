"""End-to-end draft, planner, reuse and real FFmpeg regression coverage."""
import json
import shutil
import subprocess
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent import shorts_jobs, shorts_drafts, shorts_draft_routes
from agent.shorts_composer import compose_command, scene_music, select_track, scene_tts
from agent.shorts_planner import ShortProject, quality_capabilities
from agent.shorts_studio import create_project_revision
from backend import shorts_draft_routes as web_routes


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path / 'shorts')
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'shorts/jobs.json')
    monkeypatch.setattr(shorts_jobs, 'MUSIC_DIRECTORY', tmp_path / 'music')
    monkeypatch.setattr(shorts_jobs, 'start_short_job', Mock())
    from agent import image_api
    monkeypatch.setattr(image_api, 'request', Mock(return_value={'models': [
        {'id':'test-image','enabled':True,'available':True,'capabilities':['text_to_image']}]}))
    return tmp_path


def project(**changes):
    data = {"schema_version": 2, "title": "Coffee", "duration": 10, "voice_enabled": False,
            "music_enabled": False, "briefing": "Absurd luxury coffee benefit",
            "scenes": [{"id": f"scene-{i}", "duration": 5, "video_prompt": f"Office {i}",
                        "caption": f"Caption {i}", "narration": ""} for i in range(2)]}
    data.update(changes)
    return ShortProject.model_validate(data)


def source():
    job = shorts_jobs.create_short_job(project(), chat_id='studio')
    root = shorts_jobs.SHORTS_DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (root / f'{i}.mp4').write_bytes(b'video-fixture')
        (root / f'{i}.jpg').write_bytes(b'image-fixture')
    return shorts_jobs._update_job(job['id'], status='completed',
        scene_results=[{'scene_id': f'scene-{i}', 'status': 'completed', 'path': str(root / f'{i}.mp4')} for i in range(2)],
        keyframe_results=[{'scene_id': f'scene-{i}', 'status': 'completed', 'path': str(root / f'{i}.jpg')} for i in range(2)])


def test_new_schema_caption_without_voice_and_legacy_mapping():
    p = project()
    assert p.scenes[0].narration == ''
    assert 'Caption 0' in shorts_jobs.subtitles_for_project(p)
    assert shorts_jobs.narration_for_project(p) == ''
    legacy = p.model_dump()
    legacy.pop('schema_version')
    for scene in legacy['scenes']:
        scene.pop('caption')
        scene['narration'] = 'Legacy subtitle'
    restored = ShortProject.model_validate(legacy)
    assert restored.quality == 'fast'
    assert restored.scenes[0].caption == 'Legacy subtitle'
    assert restored.scenes[0].transition.type == 'cut'
    with pytest.raises(ValidationError):
        project(unrecognized=True)


@pytest.mark.parametrize('quality,duration,valid', [('fast',20,True), ('standard',20,False), ('quality',6,False), ('quality',5,True)])
def test_quality_durations(quality, duration, valid):
    data = project().model_dump()
    data.update(quality=quality, duration=duration, scenes=[{**data['scenes'][0], 'duration':duration}])
    if valid:
        assert ShortProject.model_validate(data).quality == quality
    else:
        with pytest.raises(ValidationError):
            ShortProject.model_validate(data)


def test_draft_crud_duplicate_conflicts_and_invalid_timeline(store):
    d = shorts_drafts.save_draft()
    assert not shorts_jobs._load_jobs()
    data = d['project']
    data['scenes'].append({**data['scenes'][0], 'id': 'added'})
    data['scenes'].reverse()
    saved = shorts_drafts.save_draft(data, draft_id=d['id'], expected_version=d['version'])
    assert len(saved['project']['scenes']) == 5
    with pytest.raises(ValueError, match='reload'):
        shorts_drafts.save_draft(data, draft_id=d['id'], expected_version=d['version'])
    with pytest.raises(ValueError):
        shorts_drafts.render_draft(d['id'])
    data['scenes'].pop()
    assert len(data['scenes']) == 4
    copy = shorts_drafts.duplicate_draft(d['id'])
    assert copy['id'] != d['id']
    shorts_drafts.delete_draft(d['id'])
    with pytest.raises(KeyError):
        shorts_drafts.get_draft(d['id'])
    assert len(shorts_drafts.list_drafts()) == 1


def test_plan_preserves_constraints_without_render_and_render_creates_job(store):
    p = project(quality='quality', consistency_mode=True, character_consistency=True, music_mode='scene')
    d = shorts_drafts.save_draft(p.model_dump())
    planned = p.model_dump()
    planned.update(duration=20, voice_enabled=True, quality='fast', music_mode='global')
    provider = SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text=json.dumps(planned))))
    result = shorts_drafts.plan_draft(d['id'], provider)
    assert result['project']['duration'] == 10
    assert result['project']['voice_enabled'] is False
    assert result['project']['quality'] == 'quality'
    assert result['project']['music_mode'] == 'scene'
    assert not shorts_jobs._load_jobs()
    shorts_jobs.start_short_job.assert_not_called()
    job = shorts_drafts.render_draft(d['id'])
    shorts_jobs.start_short_job.assert_called_once_with(job['id'])
    assert len(shorts_jobs._load_jobs()) == 1


def test_planner_repairs_wrong_scene_count(store):
    from agent.shorts_planner import plan_short
    p = project().model_dump()
    wrong = deepcopy(p); wrong['scenes'] = wrong['scenes'][:1]; wrong['duration'] = 5
    provider = SimpleNamespace(complete=Mock(side_effect=[SimpleNamespace(text=json.dumps(wrong)), SimpleNamespace(text=json.dumps(p))]))
    assert len(plan_short('coffee', provider, constraints={'scene_count':2, 'duration':10, 'schema_version':2}).scenes) == 2
    assert provider.complete.call_count == 2


@pytest.mark.parametrize('change', ['narration', 'caption', 'music', 'transition', 'quality', 'video_prompt', 'camera'])
def test_project_revision_reuse(store, change):
    original = source(); data = deepcopy(original['project'])
    if change == 'quality': data['quality'] = 'standard'
    elif change == 'music': data['scenes'][0]['music'] = {'enabled':True, 'volume':0.2}
    elif change == 'transition': data['scenes'][0]['transition'] = {'type':'fade', 'duration':0.5}
    else: data['scenes'][0][change] = 'changed'
    job = create_project_revision(original['id'], ShortProject.model_validate(data))
    count = len(job['scene_results'])
    assert count == (0 if change == 'quality' else 1 if change in {'video_prompt','camera'} else 2)
    assert shorts_jobs.get_short_job(original['id']) == original


def test_anchor_invalidation_and_scene_reordering(store):
    original = source(); data = deepcopy(original['project'])
    data.update(consistency_mode=True, character_consistency=True)
    job = create_project_revision(original['id'], ShortProject.model_validate(data))
    assert not job['scene_results']
    original = shorts_jobs._update_job(job['id'], status='completed', scene_results=original['scene_results'], keyframe_results=original['keyframe_results'])
    data['scenes'].reverse()
    revised = create_project_revision(original['id'], ShortProject.model_validate(data))
    assert not revised['keyframe_results']
    assert not revised['scene_results']


def test_quality_propagates_to_t2v_i2v_and_final_dimensions():
    from agent.shorts_consistency import consistent_video_job_request
    p = project(quality='quality'); job = {'project':p.model_dump(), 'chat_id':'x','run_id':'y','chat_revision':0}
    assert shorts_jobs._scene_request(job, job['project']['scenes'][0])['payload']['quality'] == 'quality'
    assert consistent_video_job_request(job, job['project']['scenes'][0], '/frame.jpg')['payload']['quality'] == 'quality'
    job['scene_results'] = [{'scene_id':s.id, 'path':'/v.mp4', 'status':'completed'} for s in p.scenes]
    command = compose_command(job, '/out.mp4')
    width, height = quality_capabilities()['quality']['dimensions']
    assert f'scale={width}:{height}' in command[command.index('-filter_complex')+1]


def test_global_music_scene_override_volume_and_fallback(store):
    directory = shorts_jobs.MUSIC_DIRECTORY / 'energetic'; directory.mkdir(parents=True)
    (directory/'track.wav').write_bytes(b'audio')
    p = project(music_enabled=True, music_mode='scene', music_style='energetic', music_volume=0.2)
    assert scene_music(p, p.scenes[0]).volume == 0.2
    assert select_track(shorts_jobs.MUSIC_DIRECTORY, scene_music(p, p.scenes[0])).name == 'track.wav'
    from agent.shorts_planner import SceneMusic
    p.scenes[1].music = SceneMusic(volume=0.6)
    assert scene_music(p,p.scenes[1]).style == 'energetic'
    assert scene_music(p,p.scenes[1]).volume == 0.6
    p.scenes[1].music = SceneMusic(track='../outside.wav')
    with pytest.raises(ValueError): select_track(shorts_jobs.MUSIC_DIRECTORY,scene_music(p,p.scenes[1]))


def test_agent_and_web_draft_routes(store, monkeypatch):
    app = FastAPI(); shorts_draft_routes.install_routes(app); client = TestClient(app)
    d = client.post('/api/shorts/drafts', json={'project':project().model_dump()}).json()['draft']
    assert client.get('/api/shorts/drafts/'+d['id']).status_code == 200
    assert client.post('/api/shorts/drafts/'+d['id']+'/render', json={}).status_code == 202
    assert client.delete('/api/shorts/drafts/'+d['id']).status_code == 200
    calls=[]; web = FastAPI()
    web_routes.install_routes(web, lambda *args, **kw: calls.append((args,kw)) or {'draft':d})
    wc = TestClient(web)
    assert wc.post('/api/mlx/shorts/drafts',json={}).status_code == 201
    assert wc.put('/api/mlx/shorts/drafts/'+d['id'],json={'project':d['project'],'expected_version':1}).status_code == 200
    assert wc.post('/api/mlx/shorts/drafts/'+d['id']+'/plan',json={}).status_code == 200
    assert calls[-1][0][1].endswith('/plan')
    assert calls[-1][1]['timeout'] == 900


@pytest.mark.parametrize('transition', ['cut','fade','fadeblack','fadewhite','flash'])
def test_real_ffmpeg_transitions_duration_audio_and_resolution(store, transition):
    if not shutil.which('ffmpeg'): pytest.skip('ffmpeg not installed')
    clip = store/'clip.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=blue:s=64x112:r=30:d=5','-c:v','libx264',str(clip)],check=True)
    p = project(subtitles_enabled=False, music_enabled=True, music_mode='scene', music_style='energetic')
    data=p.model_dump(); data['scenes'][0]['transition']={'type':transition,'duration':0.0 if transition=='cut' else 0.5}
    data['scenes'][1]['music']={'volume':0.3, 'duck_under_voice':False, 'fade_in':0.2}
    p=ShortProject.model_validate(data)
    music=shorts_jobs.MUSIC_DIRECTORY/'energetic';music.mkdir(parents=True)
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',str(music/'tone.wav')],check=True)
    job={'project':p.model_dump(), 'scene_results':[{'scene_id':s.id,'status':'completed','path':str(clip)} for s in p.scenes]}
    out=store/'out.mp4'; cmd=compose_command(job,out)
    filters=cmd[cmd.index('-filter_complex')+1]
    assert 'volume=0.18' in filters and 'volume=0.3' in filters
    subprocess.run(cmd,cwd=store,check=True,capture_output=True)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(out)]))
    assert abs(float(info['format']['duration'])-10) < 0.05
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height']) == (576,1024)
    assert any(s['codec_type']=='audio' for s in info['streams'])


def test_scene_tts_skips_disabled_scene_and_caption(store):
    if not shutil.which('ffmpeg'): pytest.skip('ffmpeg not installed')
    p=project(voice_enabled=True)
    data=p.model_dump();data['scenes'][0].update(narration='Speak this',voice_enabled=True)
    data['scenes'][1].update(narration='Do not speak',voice_enabled=False)
    p=ShortProject.model_validate(data)
    job=shorts_jobs.create_short_job(p,chat_id='studio')
    audio=subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:duration=0.5','-f','mp3','pipe:1'])
    request=Mock(return_value=audio)
    assert scene_tts(job['id'],p,request)
    request.assert_called_once_with({'input':'Speak this','language':'de'})


def test_api_planning_never_starts_media_jobs(store, monkeypatch):
    provider=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text=json.dumps(project().model_dump()))))
    monkeypatch.setattr(shorts_draft_routes,'model_provider',lambda:provider)
    app=FastAPI();shorts_draft_routes.install_routes(app);client=TestClient(app)
    response=client.post('/api/shorts/plan',json={'prompt':'Create a 10-second coffee short','chat_id':'chat'})
    assert response.status_code == 201, response.text
    draft=response.json()['draft']
    response=client.post('/api/shorts/drafts/'+draft['id']+'/plan',json={'scene_count':2})
    assert response.status_code == 200, response.text
    assert not shorts_jobs._load_jobs()
    shorts_jobs.start_short_job.assert_not_called()


def test_missing_optional_music_warns_and_render_still_creates_job(store):
    d=shorts_drafts.save_draft(project(music_enabled=True,music_style='energetic').model_dump())
    assert not d['project']['music_enabled']
    assert 'music_unavailable' in d['warnings']
    data=d['project'];data['music_enabled']=True;data['music_track']='energetic/missing.wav'
    d=shorts_drafts.save_draft(data,draft_id=d['id'],expected_version=d['version'])
    assert d['project']['music_track'] is None
    assert 'music_track_missing' in d['warnings']
    assert not shorts_jobs._load_jobs()
    job=shorts_drafts.render_draft(d['id'])
    assert not job['project']['music_enabled']
    shorts_jobs.start_short_job.assert_called_once_with(job['id'])


def test_global_music_keeps_offset_and_local_sfx(store):
    p=project(music_enabled=True, music_mode='global', music_style='energetic', subtitles_enabled=False)
    music=shorts_jobs.MUSIC_DIRECTORY/'energetic';music.mkdir(parents=True)
    (music/'track.wav').write_bytes(b'audio')
    sfx=shorts_jobs.MUSIC_DIRECTORY.parent/'sfx';sfx.mkdir()
    (sfx/'hit.wav').write_bytes(b'audio')
    data=p.model_dump();data['scenes'][1]['sfx']={'enabled':True,'track':'hit.wav','volume':0.4,'offset':1.0}
    p=ShortProject.model_validate(data)
    job={'project':p.model_dump(),'scene_results':[{'scene_id':s.id,'path':'/v.mp4','status':'completed'} for s in p.scenes]}
    cmd=compose_command(job,store/'out.mp4');filters=cmd[cmd.index('-filter_complex')+1]
    assert 'atrim=start=5.0:duration=5' in filters
    assert 'volume=0.4,adelay=6000:all=1' in filters


def test_static_v2_captions_bypass_alignment(store, monkeypatch):
    from agent import shorts_caption_runtime as captions
    job=shorts_jobs.create_short_job(project(voice_enabled=True),chat_id='studio')
    original=Mock(return_value=job)
    monkeypatch.setattr(captions,'_ORIGINAL_RUN_COMPOSE',original)
    alignment=Mock()
    monkeypatch.setattr(captions,'_alignment_for_job',alignment)
    captions._patched_run_compose(job['id'],Mock(),Mock())
    alignment.assert_not_called()
    assert shorts_jobs.get_short_job(job['id'])['caption_alignment_status']=='scene_timed'


def test_bad_draft_store_is_never_overwritten(store):
    shorts_jobs.SHORTS_DIRECTORY.mkdir()
    path=shorts_jobs.SHORTS_DIRECTORY/'drafts.json';path.write_text('broken JSON')
    with pytest.raises(ValueError):shorts_drafts.save_draft()
    assert path.read_text()=='broken JSON'


@pytest.mark.parametrize('side', ['agent', 'web'])
def test_static_draft_routes_precede_legacy_download_route(store, side):
    """Mirror production entrypoints: legacy app.py routes are registered first."""
    from fastapi import HTTPException
    app = FastAPI()
    prefix = '/api/shorts' if side == 'agent' else '/api/mlx/shorts'
    downloads = []
    @app.get(prefix + '/{job_id}')
    def legacy_download(job_id: str):
        downloads.append(job_id)
        raise HTTPException(404, 'Short nicht gefunden')
    calls = []
    if side == 'agent':
        shorts_draft_routes.install_routes(app)
    else:
        def proxy(method, path, payload=None, **kwargs):
            calls.append((method, path))
            return {'drafts': []} if path.endswith('/drafts') else {'qualities': {}}
        web_routes.install_routes(app, proxy)
    client = TestClient(app)
    assert client.get(prefix + '/capabilities').status_code == 200
    assert client.get(prefix + '/drafts').json() == {'drafts': []}
    assert not downloads, 'static names must never be interpreted as job IDs'
    assert client.get(prefix + '/0123456789abcdef01234567').status_code == 404
    assert downloads == ['0123456789abcdef01234567']
    count = len(app.routes)
    if side == 'agent': shorts_draft_routes.install_routes(app)
    else: web_routes.install_routes(app, proxy)
    assert len(app.routes) == count


def test_planning_normalizes_optional_media_and_exact_quality_timeline(store):
    p=project(quality='quality',music_enabled=True,music_selection='auto',style_preset='luxury_commercial')
    draft=shorts_drafts.save_draft(p.model_dump())
    output=p.model_dump()
    output['scenes'][0].update(duration=6,description='Dramatic coffee reveal',video_prompt='',camera='',caption='',title='',
        sfx={'enabled':True,'track':'missing.wav','volume':0.5,'offset':0.0})
    output['scenes'][1]['transition']={'type':'fadewhite','duration':0.5}
    provider=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text=json.dumps(output))))
    planned=shorts_drafts.plan_draft(draft['id'],provider)
    value=ShortProject.model_validate(planned['project'])
    assert [s.duration for s in value.scenes]==[5,5]
    assert value.duration==10 and value.quality=='quality'
    assert value.voice_enabled is False and not value.music_enabled
    assert all(not s.sfx.enabled for s in value.scenes)
    assert value.scenes[-1].transition.type=='cut' and value.scenes[-1].transition.duration==0
    assert all(s.description and s.video_prompt and s.caption and s.title and s.camera for s in value.scenes)
    assert 'Luxury commercial' in value.visual_bible.style
    assert {'music_unavailable','sfx_unavailable','timeline_normalized'} <= set(planned['warnings'])
    assert not shorts_jobs._load_jobs()
    shorts_jobs.start_short_job.assert_not_called()
    assert shorts_drafts.render_draft(draft['id'])['id']


def test_optional_defaults_do_not_hide_real_core_blockers(store):
    from agent.shorts_normalization import normalize_short_for_available_runtime
    data=project().model_dump()
    data.update(captions={'position':'invalid','size':1000,'style':'unknown'},music_enabled=True,music_track='outside.wav')
    data['scenes'][0]['sfx']={'enabled':True,'track':None,'volume':0.5,'offset':0.0}
    normalized,warnings=normalize_short_for_available_runtime(data)
    p=ShortProject.model_validate(normalized)
    assert p.captions.position=='bottom' and p.captions.style=='bold' and p.captions.size==54
    assert not p.music_enabled and not p.scenes[0].sfx.enabled
    assert warnings
    malformed=deepcopy(data)
    malformed['scenes'][0].update(transition='invalid', music='invalid', sfx=None)
    fixed=ShortProject.model_validate(normalize_short_for_available_runtime(malformed)[0])
    assert fixed.scenes[0].transition.type=='cut' and fixed.scenes[0].music is None
    assert not fixed.scenes[0].sfx.enabled
    bad=deepcopy(data);bad['duration']=11
    with pytest.raises(ValueError,match='sum exactly'):
        ShortProject.model_validate(normalize_short_for_available_runtime(bad)[0])
    bad=deepcopy(data);bad['scenes'][0]['video_prompt']=''
    with pytest.raises(ValueError,match='video_prompt'):
        ShortProject.model_validate(normalize_short_for_available_runtime(bad)[0])


def test_auto_music_uses_only_local_library_and_preserves_explicit_settings(store):
    from agent.shorts_normalization import normalize_short_for_available_runtime
    root=shorts_jobs.MUSIC_DIRECTORY/'energetic';root.mkdir(parents=True)
    (root/'local.wav').write_bytes(b'audio')
    data=project(music_enabled=True,music_selection='auto').model_dump()
    normalized,warnings=normalize_short_for_available_runtime(data)
    p=ShortProject.model_validate(normalized)
    assert p.music_enabled and p.music_style=='energetic'
    assert select_track(shorts_jobs.MUSIC_DIRECTORY,scene_music(p,p.scenes[0]))==root/'local.wav'
    data.update(music_selection='custom',music_track='energetic/local.wav',music_volume=0.37,voice_enabled=False,quality='quality')
    normalized,_=normalize_short_for_available_runtime(data,planning=True,scene_count=2)
    assert normalized['music_track']=='energetic/local.wav' and normalized['music_volume']==0.37
    assert normalized['voice_enabled'] is False and normalized['quality']=='quality'


def test_incompatible_explicit_duration_count_is_not_silently_changed(store):
    data=project(quality='quality').model_dump();data['duration']=11
    draft=shorts_drafts.save_draft(data)
    provider=SimpleNamespace(complete=Mock())
    with pytest.raises(ValueError,match='cannot be divided'):
        shorts_drafts.plan_draft(draft['id'],provider)
    provider.complete.assert_not_called()
    assert not shorts_jobs._load_jobs()
