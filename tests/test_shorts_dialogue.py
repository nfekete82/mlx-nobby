"""Cast dialogue validation, speech routing and ordered scene audio."""
import io
import math
from pathlib import Path
import shutil
import struct
import subprocess
from unittest.mock import Mock
import wave

import pytest
from pydantic import ValidationError

from agent import shorts_composer, shorts_jobs
from agent.shorts_planner import DialogueLine, ShortProject, _planning_messages
from agent.shorts_normalization import normalize_short_for_available_runtime


def payload():
    return {
        'schema_version': 2, 'title': 'Conversation', 'duration': 5,
        'voice': 'global', 'voice_speed': 1.2, 'music_enabled': False,
        'cast': [{'id': 'nobby', 'name': 'Nobby', 'voice': 'Nobby Voice'},
                 {'id': 'lisa', 'name': 'Lisa', 'voice': 'Lisa Voice'}],
        'scenes': [{'id': 'scene-1', 'duration': 5, 'video_prompt': 'Two people talking',
                    'narration': 'Do not speak this summary', 'dialogue': [
                        {'speaker': 'nobby', 'text': 'A'}, {'speaker': 'lisa', 'text': 'B'},
                        {'speaker': 'nobby', 'text': 'C'}]}],
    }


def test_dialogue_cast_and_roundtrip():
    project = ShortProject.model_validate(payload())
    assert [line.speaker for line in project.scenes[0].dialogue] == ['nobby', 'lisa', 'nobby']
    assert ShortProject.model_validate(project.model_dump()) == project
    assert project.voice_for_speaker('nobby') == 'Nobby Voice'
    project.cast[0].voice = None
    assert project.voice_for_speaker('nobby') == 'global'
    project.voice = None
    assert project.voice_for_speaker('nobby') is None
    assert project.voice_for_speaker(None) is None


@pytest.mark.parametrize('cast', [[], payload()['cast']])
@pytest.mark.parametrize('draft', [True, False])
def test_unknown_dialogue_speaker_rejected(cast, draft):
    data = payload(); data['cast'] = cast
    data['scenes'][0]['dialogue'][1]['speaker'] = 'missing'
    with pytest.raises(ValidationError, match='dialogue speaker .*not present in cast'):
        ShortProject.model_validate(data, context={'draft': draft})


@pytest.mark.parametrize('line', [
    {'speaker': '', 'text': 'A'}, {'speaker': 'unsafe/path', 'text': 'A'},
    {'speaker': 'nobby', 'text': '  '}, {'speaker': 'nobby', 'text': 'a' * 1001},
    {'speaker': 'nobby', 'text': 123}, {'speaker': 'nobby', 'text': 'A', 'voice': 'fake'},
])
def test_dialogue_strict_validation(line):
    with pytest.raises(ValidationError):
        DialogueLine.model_validate(line)


def test_dialogue_limit_and_whitespace():
    data = payload(); data['scenes'][0]['dialogue'] *= 22
    with pytest.raises(ValidationError):
        ShortProject.model_validate(data)
    assert DialogueLine(speaker=' nobby ', text=' Hello ').text == 'Hello'


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_scenes_without_cast_or_dialogue(version):
    data = payload(); data['schema_version'] = version; data.pop('cast')
    data['scenes'][0].pop('dialogue')
    project = ShortProject.model_validate(data)
    assert project.scenes[0].dialogue == []
    assert project.voice_for_scene(project.scenes[0]) == 'global'


@pytest.fixture
def audio_store(tmp_path, monkeypatch):
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path)
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'jobs.json')
    monkeypatch.setattr(shorts_jobs, 'get_short_job', lambda _: {'cancel_requested': False})
    return tmp_path


def mock_composition(monkeypatch, durations):
    monkeypatch.setattr(shorts_composer.subprocess, 'check_output', Mock(side_effect=[str(d) for d in durations]))
    commands = []
    def compose(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b'mixed')
    monkeypatch.setattr(shorts_jobs, '_run_ffmpeg', compose)
    return commands


def test_ordered_dialogue_tts_and_concat(audio_store, monkeypatch):
    project = ShortProject.model_validate(payload())
    commands = mock_composition(monkeypatch, [0.4, 0.7, 0.5])
    request = Mock(return_value=b'audio')
    assert shorts_composer.scene_tts('job', project, request) == b'mixed'
    calls = [call.args[0] for call in request.call_args_list]
    assert calls == [dict(input=text, voice=voice, language='de', speed=1.2)
                     for text, voice in [('A', 'Nobby Voice'), ('B', 'Lisa Voice'), ('C', 'Nobby Voice')]]
    command = commands[0]
    paths = [command[i + 1] for i, arg in enumerate(command) if arg == '-i']
    assert [Path(p).name for p in paths] == [f'voice-scene-1-dialogue-{i}-{speaker}.mp3'
                                          for i, speaker in enumerate(['nobby', 'lisa', 'nobby'])]
    filters = command[command.index('-filter_complex') + 1]
    assert '[d1_0][d1_1][d1_2]concat=n=3:v=0:a=1[dialogue1]' in filters
    assert filters.count('apad=pad_dur=0.18') == 2
    assert 'apad=pad_dur=0[d1_2]' in filters


def test_legacy_tts_payload(audio_store, monkeypatch):
    data = payload(); data['scenes'][0].pop('dialogue'); data['scenes'][0]['speaker'] = 'lisa'
    project = ShortProject.model_validate(data)
    mock_composition(monkeypatch, [1])
    request = Mock(return_value=b'audio')
    shorts_composer.scene_tts('job', project, request)
    request.assert_called_once_with({'input': 'Do not speak this summary', 'voice': 'Lisa Voice', 'language': 'de', 'speed': 1.2})


def test_dialogue_duration_includes_pauses(audio_store, monkeypatch):
    project = ShortProject.model_validate(payload())
    commands = mock_composition(monkeypatch, [2, 2, 2])
    with pytest.raises(shorts_composer.VoiceoverDurationError) as error:
        shorts_composer.scene_tts('job', project, Mock(return_value=b'audio'))
    assert error.value.diagnosis['error_audio_duration'] == pytest.approx(6.36)
    assert not commands


def test_dialogue_only_planning_keeps_voice_enabled():
    data = payload(); data['scenes'][0]['narration'] = ''
    normalized, _ = normalize_short_for_available_runtime(data, planning=True)
    assert normalized['scenes'][0].get('voice_enabled', True) is True
    project = ShortProject.model_validate(normalized)
    assert shorts_jobs.narration_for_project(project) == 'A\nB\nC'
    prompt = _planning_messages('Nobby talks to Lisa')[0]['content']
    assert 'Use only ids present in project cast' in prompt
    assert 'voice belongs' in prompt


@pytest.mark.parametrize('version', [1, 2])
def test_dialogue_only_runs_through_job_tts(tmp_path, monkeypatch, version):
    monkeypatch.setattr(shorts_jobs, 'SHORTS_DIRECTORY', tmp_path)
    monkeypatch.setattr(shorts_jobs, 'SHORTS_JOBS_FILE', tmp_path / 'jobs.json')
    data = payload(); data['schema_version'] = version; data['scenes'][0]['narration'] = ''
    project = ShortProject.model_validate(data)
    job = shorts_jobs.create_short_job(project, chat_id='test')
    speech = Mock(return_value=b'mixed')
    monkeypatch.setattr(shorts_composer, 'scene_tts', speech)
    request = Mock(side_effect=AssertionError('legacy aggregate TTS must not run'))
    result = shorts_jobs._run_tts(job['id'], Mock(), request)
    assert result['tts_status'] == 'completed'
    speech.assert_called_once()


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_real_audio_order_pauses_and_mixed_formats(audio_store):
    data = payload(); data['voice_speed'] = 1.0
    project = ShortProject.model_validate(data)
    def tone(seconds, frequency, rate, channels):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(channels); output.setsampwidth(2); output.setframerate(rate)
            output.writeframes(b''.join(struct.pack('<h', int(12000 * math.sin(2 * math.pi * frequency * i / rate))) * channels
                                       for i in range(round(seconds * rate))))
        return buffer.getvalue()
    request = Mock(side_effect=[tone(.4, 220, 24000, 1), tone(.7, 440, 48000, 2), tone(.5, 880, 16000, 1)])
    mixed = shorts_composer.scene_tts('job', project, request)
    path = audio_store / 'mixed.mp3'; path.write_bytes(mixed)
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 's16le', '-ac', '1', '-ar', '24000', 'pipe:1'])
    samples = [value[0] for value in struct.iter_unpack('<h', decoded)]
    assert len(samples) / 24000 == pytest.approx(5, abs=.05)
    for start, end in [(.43, .55), (1.31, 1.43), (2.1, 4.9)]:
        assert max(abs(v) for v in samples[int(start * 24000):int(end * 24000)]) < 100
    for start, end, frequency in [(.1, .3, 220), (.7, 1.1, 440), (1.6, 1.85, 880)]:
        segment = samples[int(start * 24000):int(end * 24000)]
        crossings = sum(a < 0 <= b for a, b in zip(segment, segment[1:]))
        assert crossings / (end - start) == pytest.approx(frequency, abs=10)


def test_dialogue_compression_and_following_scene_offset(audio_store, monkeypatch):
    data = payload(); data['duration'] = 10
    data['scenes'].append({'id': 'scene-2', 'duration': 5, 'video_prompt': 'Listener', 'narration': 'Next'})
    project = ShortProject.model_validate(data)
    commands = mock_composition(monkeypatch, [1.8, 1.8, 1.4, 1])
    shorts_composer.scene_tts('job', project, Mock(return_value=b'audio'))
    filters = commands[0][commands[0].index('-filter_complex') + 1]
    assert '[dialogue1]aresample=48000,atempo=1.072000000' in filters
    assert '[3:a]aresample=48000,atrim=duration=5' in filters
    assert 'adelay=5000:all=1' in filters


@pytest.mark.parametrize('project_voice', ['global', None])
def test_dialogue_tts_voice_fallback(audio_store, monkeypatch, project_voice):
    data = payload(); data['cast'][0]['voice'] = None; data['voice'] = project_voice
    project = ShortProject.model_validate(data)
    mock_composition(monkeypatch, [1, 1, 1])
    request = Mock(return_value=b'audio')
    shorts_composer.scene_tts('job', project, request)
    first = request.call_args_list[0].args[0]
    if project_voice:
        assert first['voice'] == project_voice
    else:
        assert 'voice' not in first


def test_dialogue_cancellation_stops_before_next_turn(audio_store, monkeypatch):
    project = ShortProject.model_validate(payload())
    mock_composition(monkeypatch, [1, 1, 1])
    cancelled = {'cancel_requested': False}
    monkeypatch.setattr(shorts_jobs, 'get_short_job', lambda _: cancelled)
    def request(payload):
        cancelled['cancel_requested'] = True
        return b'audio'
    speech = Mock(side_effect=request)
    with pytest.raises(shorts_jobs._ComposeCancelled):
        shorts_composer.scene_tts('job', project, speech)
    speech.assert_called_once()
