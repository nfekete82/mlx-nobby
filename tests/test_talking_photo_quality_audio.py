import hashlib
import unittest
from unittest import mock

from agent import talking_photo_quality


class TalkingPhotoQualityAudioTests(unittest.TestCase):
    def test_custom_voice_final_lipsync_uses_ltx_video_and_same_wav(self):
        video = b"ltx-video-bytes"
        wav = b"RIFF" + b"\x00" * 80
        expected_video = b"musetalk-video-bytes"
        expected_timing = "total=1.23"
        expected_avatar_key = hashlib.sha256(video).hexdigest()[:24]

        with mock.patch(
            "agent.talking_photo_quality.talking_photo._musetalk_lipsync",
            return_value=(expected_video, expected_timing),
        ) as lipsync:
            result = talking_photo_quality._finalize_custom_voice_lipsync(video, wav)

        self.assertEqual(result, (expected_video, expected_timing))
        lipsync.assert_called_once_with(video, wav, expected_avatar_key)


if __name__ == "__main__":
    unittest.main()
