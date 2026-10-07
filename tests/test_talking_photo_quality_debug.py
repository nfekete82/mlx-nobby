import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from unittest import mock
import wave

import pytest

spec = importlib.util.spec_from_file_location('talking_photo_debug', 'scripts/debug-talking-photo-quality.py')
debug = importlib.util.module_from_spec(spec)
spec.loader.exec_module(debug)


def test_debug_freezes_tts_once_and_resume_checks_input_hashes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\x88\x13' * 1600)
    audio = buffer.getvalue()
    with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {}, clear=True):
        root = Path(directory)
        image = root / 'portrait.png'
        image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
        output = root / 'suite'
        argv = ['debug', '--image', str(image), '--text', 'Hallo!', '--voice', 'Julia',
                '--seeds', '42', '--output', str(output), '--prepare-only']
        with mock.patch('sys.argv', argv), \
             mock.patch.object(debug.talking_photo, '_request_tts', return_value=b'native TTS') as tts, \
             mock.patch.object(debug.talking_photo, '_audio_to_wav', return_value=audio):
            assert debug.main() == 0
            tts.assert_called_once_with({'input': 'Hallo!', 'language': 'german', 'voice': 'Julia'})
        frozen = (output / 'frozen.wav').read_bytes()
        with mock.patch('sys.argv', argv + ['--resume']), \
             mock.patch.object(debug.talking_photo, '_request_tts') as tts:
            assert debug.main() == 0
            tts.assert_not_called()
        assert (output / 'frozen.wav').read_bytes() == frozen
        manifest = json.loads((output / 'inputs.json').read_text())
        assert manifest['tts_request']['voice'] == 'Julia'
        (output / 'frozen.wav').write_bytes(b'changed')
        with mock.patch('sys.argv', argv + ['--resume']), pytest.raises(SystemExit, match='Frozen input was changed'):
            debug.main()
