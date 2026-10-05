import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from agent import talking_photo_quality


class TalkingPhotoQualityAudioTests(unittest.TestCase):
    @staticmethod
    def _wav_bytes(samples, sample_rate=16000):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            pcm = bytearray()
            for sample in samples:
                pcm.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
            handle.writeframes(bytes(pcm))
        return buffer.getvalue()

    def test_analyze_wav_reports_leading_and_trailing_silence(self):
        sample_rate = 16000
        samples = (
            [0] * int(sample_rate * 0.10)
            + [5000] * int(sample_rate * 0.20)
            + [0] * int(sample_rate * 0.15)
        )
        stats = talking_photo_quality._analyze_wav(self._wav_bytes(samples, sample_rate))

        self.assertEqual(stats["sample_rate"], 16000)
        self.assertEqual(stats["channels"], 1)
        self.assertAlmostEqual(stats["duration_seconds"], 0.45, places=2)
        self.assertAlmostEqual(stats["leading_silence_ms"], 100.0, delta=10.0)
        self.assertAlmostEqual(stats["trailing_silence_ms"], 150.0, delta=10.0)
        self.assertIsNotNone(stats["peak_dbfs"])
        self.assertIsNotNone(stats["active_rms_dbfs"])

    def test_persist_audio_diagnostics_keeps_wav_and_metadata(self):
        wav = self._wav_bytes([1000] * 1600)
        stats = talking_photo_quality._analyze_wav(wav)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            talking_photo_quality,
            "AUDIO_DEBUG_ROOT",
            Path(directory),
        ):
            result = talking_photo_quality._persist_audio_diagnostics(
                "a" * 24,
                "Pervin",
                "de",
                wav,
                stats,
            )

            wav_path = Path(result["wav_path"])
            metadata_path = Path(result["metadata_path"])
            self.assertEqual(wav_path.read_bytes(), wav)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["voice"], "Pervin")
        self.assertEqual(metadata["language"], "de")
        self.assertEqual(metadata["stats"]["sample_rate"], 16000)


if __name__ == "__main__":
    unittest.main()
