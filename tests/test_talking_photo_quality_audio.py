import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent import talking_photo_quality


class TalkingPhotoQualityAudioTests(unittest.TestCase):
    def test_custom_voice_trim_preserves_internal_pauses_filter_shape(self):
        original = b"RIFF" + b"\x00" * 80
        trimmed = b"RIFF" + b"\x01" * 80
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            Path(command[-1]).write_bytes(trimmed)
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("agent.talking_photo_quality.shutil.which", return_value="/usr/bin/ffmpeg"), \
             mock.patch("agent.talking_photo_quality.subprocess.run", side_effect=fake_run):
            result = talking_photo_quality._trim_custom_voice_wav(
                original,
                Path(directory),
            )

        self.assertEqual(result, trimmed)
        command = captured["command"]
        audio_filter = command[command.index("-af") + 1]
        self.assertEqual(audio_filter.count("silenceremove="), 2)
        self.assertEqual(audio_filter.count("areverse"), 2)
        self.assertNotIn("stop_periods", audio_filter)
        self.assertIn("start_threshold=-45dB", audio_filter)


if __name__ == "__main__":
    unittest.main()
