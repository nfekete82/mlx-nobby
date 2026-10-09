import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from agent import talking_photo_quality
from agent.talking_photo_audio import prepend_lead_in, validate_wav


class TalkingPhotoQualityAudioTests(unittest.TestCase):
    def test_direct_ltx_mode_skips_musetalk_and_returns_native_video(self):
        details = {"elapsed_seconds": 1.25}
        with mock.patch.object(
            talking_photo_quality.talking_photo_ltx,
            'generate',
            return_value=(b'native-ltx-video', details),
        ), mock.patch.object(
            talking_photo_quality.talking_photo,
            '_musetalk_lipsync',
        ) as lipsync:
            video, result = talking_photo_quality.generate(
                'job',
                cancelled=lambda: False,
                apply_lipsync=False,
            )

        self.assertEqual(video, b'native-ltx-video')
        self.assertEqual(result["engine"], "ltx")
        self.assertIsNone(result["lipsync"])
        lipsync.assert_not_called()

    def test_changed_conditioning_audio_is_rejected_before_the_lip_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'conditioning.wav'
            path.write_bytes(b'changed audio')
            details = {'audio_path': str(path), 'conditioning_audio_sha256': 'original hash'}
            with mock.patch.object(talking_photo_quality.talking_photo_ltx, 'generate', return_value=(b'video', details)), \
                 mock.patch.object(talking_photo_quality.talking_photo, '_musetalk_lipsync') as lipsync:
                with self.assertRaisesRegex(RuntimeError, 'Conditioning-WAV wurde verändert'):
                    talking_photo_quality.generate('job', cancelled=lambda: False)
                lipsync.assert_not_called()

    def test_cancelled_a2v_output_is_not_sent_to_the_lip_renderer(self):
        with mock.patch.object(talking_photo_quality.talking_photo_ltx, 'generate', return_value=(b'video', {})), \
             mock.patch.object(talking_photo_quality.talking_photo, '_musetalk_lipsync') as lipsync:
            with self.assertRaises(talking_photo_quality.talking_photo_ltx.QualityCancelled):
                talking_photo_quality.generate('job', cancelled=lambda: True)
            lipsync.assert_not_called()

    def test_tts_uses_qwen_language_names_without_changing_shared_speech_defaults(self):
        for supplied, expected in [('de', 'german'), ('de-DE', 'german'), ('en', 'english'),
                                   ('fr', 'french'), ('German', 'German'), ('auto', 'auto')]:
            with self.subTest(language=supplied):
                self.assertEqual(talking_photo_quality.tts_language(supplied), expected)

    @staticmethod
    def _wav_bytes(samples, sample_rate=16000):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(b''.join(int(s).to_bytes(2, 'little', signed=True) for s in samples))
        return buffer.getvalue()

    def test_analyze_wav_reports_leading_and_trailing_silence(self):
        wav = self._wav_bytes([0] * 1600 + [5000] * 3200 + [0] * 2400)
        stats = talking_photo_quality._analyze_wav(wav)
        self.assertEqual(stats['sample_rate'], 16000)
        self.assertEqual(stats['channels'], 1)
        self.assertAlmostEqual(stats['duration_seconds'], 0.45, places=2)
        self.assertAlmostEqual(stats['leading_silence_ms'], 100, delta=10)
        self.assertAlmostEqual(stats['trailing_silence_ms'], 150, delta=10)
        self.assertIsNotNone(stats['active_rms_dbfs'])

    def test_validation_rejects_empty_silent_and_wrong_rate_audio(self):
        for samples, rate in [([], 16000), ([0] * 16000, 16000), ([1000] * 1600, 24000)]:
            with self.subTest(rate=rate, count=len(samples)), self.assertRaises(RuntimeError):
                validate_wav(self._wav_bytes(samples, rate))

    def test_standard_and_custom_voices_use_native_audio_without_trim_or_tempo(self):
        # A long pre-roll must survive unchanged, including Pervin and Julia.
        wav = self._wav_bytes([0] * 8960 + [5000] * 8000)
        for voice in [None, 'Pervin', 'Julia', 'Another Voice']:
            with self.subTest(voice=voice), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requests, conditioning = [], []
                def tts(payload):
                    requests.append(payload)
                    return b'TTS audio'
                def generate(*args, **kwargs):
                    conditioning.append(args[3])
                    return b'\x00\x00\x00\x18ftyp' + b'0' * 40, {'seed': 42}
                with mock.patch.object(talking_photo_quality.talking_photo, 'ROOT', root), \
                     mock.patch.object(talking_photo_quality.talking_photo, 'OUTPUT', root / 'videos'), \
                     mock.patch.object(talking_photo_quality, 'AUDIO_DEBUG_ROOT', root / 'audio-debug'), \
                     mock.patch.object(talking_photo_quality.talking_photo, '_update_job'), \
                     mock.patch.object(talking_photo_quality.talking_photo, '_cancelled', return_value=False), \
                     mock.patch.object(talking_photo_quality.talking_photo, '_request_tts', side_effect=tts), \
                     mock.patch.object(talking_photo_quality.talking_photo, '_audio_to_wav', return_value=wav), \
                     mock.patch.object(talking_photo_quality.talking_photo_ltx, 'debug_directory', return_value=None), \
                     mock.patch.object(talking_photo_quality, 'generate', side_effect=generate):
                    talking_photo_quality._run_quality_job('a' * 24, b'image', '.png',
                        {'text': 'Hallo!', 'language': 'de', 'voice': voice, 'speed': 1.0})
                expected = {'input': 'Hallo!', 'language': 'german'}
                if voice:
                    expected['voice'] = voice
                self.assertEqual(requests, [expected])
                self.assertEqual(conditioning, [wav])
                self.assertTrue((root / 'videos' / ('a' * 24 + '.mp4')).is_file())

    def test_persist_audio_diagnostics_keeps_native_timing(self):
        wav = self._wav_bytes([1000] * 1600)
        stats = talking_photo_quality._analyze_wav(wav)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            talking_photo_quality, 'AUDIO_DEBUG_ROOT', Path(directory)):
            result = talking_photo_quality._persist_audio_diagnostics(
                'a' * 24, 'Pervin', 'de', 'native', 1.0, 1.0, None, wav, stats)
            self.assertEqual(Path(result['wav_path']).read_bytes(), wav)
            metadata = json.loads(Path(result['metadata_path']).read_text())
        self.assertEqual(metadata['tts_speed'], 1.0)
        self.assertEqual(metadata['postprocess_tempo'], 1.0)
        self.assertIsNone(metadata['target_leading_silence_ms'])
