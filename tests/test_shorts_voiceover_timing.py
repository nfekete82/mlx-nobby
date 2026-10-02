"""Scene timing, safe diagnostics and video reuse after TTS/compose failures."""
import io
import math
import struct
import shutil
import subprocess
import wave
from unittest.mock import Mock

import pytest

from agent import shorts_composer, shorts_jobs, shorts_studio
from agent.shorts_planner import ShortProject
from agent.shorts_studio_routes import _history_summary


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path / 'shorts')
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'shorts/jobs.json')
    return tmp_path


def project():
    return ShortProject.model_validate({
        'schema_version': 2, 'title': 'Timing', 'duration': 10,
        'voice_enabled': True, 'music_enabled': False, 'subtitles_enabled': False,
        'scenes': [{'id': f'scene_{i}', 'duration': 5, 'video_prompt': f'Room {i}',
                    'narration': f'Speak {i}', 'caption': ''} for i in (1, 2)]
    })


def mock_mix(monkeypatch, durations):
    probe = Mock(side_effect=[str(d) for d in durations])
    monkeypatch.setattr(shorts_composer.subprocess, 'check_output', probe)
    commands = []

    def ffmpeg(command, **kwargs):
        from pathlib import Path
        commands.append(command)
        Path(command[-1]).write_bytes(b'output')

    monkeypatch.setattr(shorts_jobs, '_run_ffmpeg', ffmpeg)
    return commands


@pytest.mark.parametrize('duration,compressed', [
    (5.0, False), (4.9, False), (5.04, False), (5.05, False), (5.2, True), (5.4, True), (5.75, True)
])
def test_scene_timing(store, monkeypatch, duration, compressed):
    p = project()
    job = shorts_jobs.create_short_job(p, chat_id='timing')
    commands = mock_mix(monkeypatch, [5, duration])
    request = Mock(return_value=b'audio')
    assert shorts_composer.scene_tts(job['id'], p, request) == b'output'
    filters = commands[0][commands[0].index('-filter_complex') + 1]
    assert '[0:a]aresample=48000,atrim' in filters
    assert filters.count('atempo=') == int(compressed)
    if compressed:
        assert f'[1:a]aresample=48000,atempo={duration / 5:.9f},asetpts=N/SR/TB,atrim' in filters
    assert request.call_args_list[1].args[0] == {'input': 'Speak 2', 'language': 'de'}
    assert p.voice_speed == 1


@pytest.mark.parametrize('status', ['queued', 'video_completed'])
@pytest.mark.parametrize('duration', [5.751, 8.0])
def test_over_limit_persists_safe_scene_diagnosis(store, monkeypatch, status, duration):
    p = project()
    job = shorts_jobs.create_short_job(p, chat_id='timing')
    videos = []
    for scene in p.scenes:
        path = store / f'{scene.id}.mp4'
        path.write_bytes(b'video')
        videos.append({'scene_id': scene.id, 'status': 'completed', 'path': str(path)})
    shorts_jobs._update_job(job['id'], status=status, scene_results=videos, current_scene=2)
    commands = mock_mix(monkeypatch, [5, duration])
    video = Mock(side_effect=AssertionError('video rendering must not run'))
    result = shorts_jobs.run_short_job(job['id'], request_fn=video,
        tts_request_fn=Mock(return_value=b'audio'), poll_interval=0)
    assert result['status'] == 'failed'
    assert result['tts_status'] == 'failed'
    assert result['error_code'] == 'VOICEOVER_TOO_LONG'
    assert result['error_stage'] == 'tts'
    assert result['error_scene_id'] == 'scene_2'
    assert result['error_scene_number'] == 2
    assert result['error_audio_duration'] == duration
    assert result['error_scene_duration'] == 5
    assert 'scene_2' in result['error'] and f'{duration:.2f}s for 5.00s' in result['error']
    assert not commands
    summary = _history_summary(result, root_id=job['id'], revision_count=0)
    assert summary['error_audio_duration'] == duration
    assert result['scene_results'] == videos
    assert all((store / f'{s.id}.mp4').read_bytes() == b'video' for s in p.scenes)
    video.assert_not_called()


@pytest.mark.parametrize('stage', ['tts', 'compose'])
def test_retry_reuses_completed_videos(store, monkeypatch, stage):
    from agent import shorts_preflight
    monkeypatch.setattr(shorts_preflight, 'preflight_project', lambda p, **kwargs: {'warnings': []})
    monkeypatch.setattr(shorts_jobs, 'start_short_job', Mock())
    p = project()
    job = shorts_jobs.create_short_job(p, chat_id='timing')
    results = []
    for scene in p.scenes:
        path = store / f'{scene.id}.mp4'
        path.write_bytes(b'video')
        results.append({'scene_id': scene.id, 'status': 'completed', 'path': str(path)})
    shorts_jobs._update_job(job['id'], scene_results=results, current_scene=2,
        status='failed', phase='tts' if stage == 'tts' else 'compose',
        tts_status='failed' if stage == 'tts' else 'completed', error='failure')
    retry = shorts_studio.retry_short_job(job['id'])
    assert retry['scene_results'] == results
    commands = mock_mix(monkeypatch, [5, 5.4])
    video = Mock(side_effect=AssertionError('LTX must not run'))
    result = shorts_jobs.run_short_job(retry['id'], request_fn=video,
        tts_request_fn=Mock(return_value=b'audio'), compose_fn=shorts_jobs._run_ffmpeg,
        poll_interval=0)
    assert result['status'] == 'completed'
    assert result['scene_results'] == results
    assert len(commands) == 2  # Audio mix and final composition only.
    video.assert_not_called()
    assert shorts_jobs.get_short_job(job['id'])['status'] == 'failed'


@pytest.mark.parametrize('global_disabled', [True, False])
def test_voice_disabled(store, monkeypatch, global_disabled):
    p = project()
    if global_disabled:
        p.voice_enabled = False
    else:
        for scene in p.scenes:
            scene.voice_enabled = False
    job = shorts_jobs.create_short_job(p, chat_id='timing')
    request = Mock(side_effect=AssertionError('speech must not run'))
    result = shorts_jobs._run_tts(job['id'], Mock(), request)
    assert result['tts_status'] == 'disabled'
    request.assert_not_called()


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_real_ffmpeg_compression_preserves_timeline(store):
    p = project()
    p.scenes[0].voice_enabled = False
    job = shorts_jobs.create_short_job(p, chat_id='timing')
    # WAV gives an exact 5.4 s probe, independent of MP3 encoder padding.
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
        audio.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * 220 * i / 24000)))
                                   for i in range(int(5.4 * 24000))))
    mixed = shorts_composer.scene_tts(job['id'], p, Mock(return_value=buffer.getvalue()))
    output = store / 'mixed.mp3'
    output.write_bytes(mixed)
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(output)], text=True))
    assert abs(duration - 10) < 0.05
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output),
        '-f', 's16le', '-ac', '1', '-ar', '24000', 'pipe:1'])
    samples = [v[0] for v in struct.iter_unpack('<h', decoded)]
    assert max(abs(v) for v in samples[24000:4 * 24000]) < 100
    assert max(abs(v) for v in samples[9 * 24000:int(9.8 * 24000)]) > 1000
