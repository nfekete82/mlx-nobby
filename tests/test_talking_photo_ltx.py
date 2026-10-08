import unittest
from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave
from unittest import mock

from agent import talking_photo_ltx, talking_photo_quality


class TalkingPhotoLtxTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "requires ffmpeg")
    def test_padding_never_rounds_below_the_requested_video_frame_span(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.wav", Path(directory) / "padded.wav"
            pcm = b"\0\0" * 160 + b"\x88\x13" * 1440
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            for frames in (9, 17, 25, 33, 73, 81, 241, 361, 481):
                with self.subTest(frames=frames):
                    talking_photo_ltx._pad_audio(source, target, frames / 24)
                    with wave.open(str(target)) as wav:
                        count = wav.getnframes()
                        padded = wav.readframes(count)
                    self.assertEqual(int(count / 16000 * 24), frames)
                    self.assertGreaterEqual(count / 16000, frames / 24)
                    self.assertLess(count / 16000 - frames / 24, 1 / 16000)
                    self.assertEqual(padded[:len(pcm)], pcm)
                    self.assertFalse(any(padded[len(pcm):]))

    def test_seed_override_is_independent_of_job_id_including_zero(self):
        for seed in [0, 42, 1234, 1337, 2026, 858797624]:
            with self.subTest(seed=seed), mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_SEED": str(seed)}):
                self.assertEqual(talking_photo_ltx.resolve_seed("a" * 24), seed)
                self.assertEqual(talking_photo_ltx.resolve_seed("b" * 24), seed)

    def test_invalid_seed_fails_instead_of_silently_randomizing(self):
        for value in ["", "no", "42.5", "-1", "2147483648"]:
            with self.subTest(value=value), mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_SEED": value}):
                with self.assertRaisesRegex(RuntimeError, "LTX_TALKING_PHOTO_SEED"):
                    talking_photo_ltx.resolve_seed("a" * 24)

    def test_unset_seed_retains_previous_job_id_behavior(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(talking_photo_ltx.resolve_seed("e6b449300b4054a0688e9cb8"), 1698062900)

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires ffmpeg")
    def test_conditioning_file_command_padding_and_bundle_survive_work_cleanup(self):
        buffer = io.BytesIO()
        pcm = b"\0\0" * 1600 + b"\x88\x13" * 3200
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        commands = []
        native_video = b"\0\0\0\x18ftyp" + b"0" * 40
        final_video = b"\0\0\0\x18ftyp" + b"1" * 40
        real_popen = subprocess.Popen
        def popen(command, **kwargs):
            if "--output" not in command:
                return real_popen(command, **kwargs)
            commands.append(command)
            Path(command[command.index("--output") + 1]).write_bytes(native_video)
            process = mock.Mock(returncode=0)
            process.communicate.return_value = ("rendered", None)
            return process
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, bundle = root / "work", root / "bundle"
            with mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_SEED": "42"}), \
                 mock.patch.object(talking_photo_ltx, "provider_health", return_value={"ready": True}), \
                 mock.patch.object(talking_photo_ltx, "_image_size", return_value=(640, 640)), \
                 mock.patch.object(talking_photo_ltx.runtime_coordinator, "video_runtime", return_value=nullcontext()), \
                 mock.patch.object(talking_photo_quality.talking_photo, "_musetalk_lipsync", return_value=(final_video, "test")) as lipsync, \
                 mock.patch.object(talking_photo_ltx.subprocess, "Popen", side_effect=popen):
                # A bogus duration must never cause the actual speech to be cut.
                video, details = talking_photo_quality.generate(
                    "a" * 24, b"portrait", ".png", buffer.getvalue(), 0.01, work,
                    cancelled=lambda: False, debug_dir=bundle)
            shutil.rmtree(work)
            command = commands[0]
            conditioning = Path(command[command.index("--audio") + 1])
            lipsync.assert_called_once_with(native_video, conditioning.read_bytes(), "quality-" + hashlib.sha256(native_video).hexdigest()[:24])
            self.assertEqual(video, final_video)
            self.assertEqual(command[0], str(talking_photo_ltx.RUNTIME_PYTHON))
            self.assertEqual(command[command.index("--model") + 1], str(talking_photo_ltx.MODEL_DIR))
            self.assertEqual(int(command[command.index("--frames") + 1]), 9)
            self.assertEqual(int(command[command.index("--fps") + 1]), 24)
            self.assertEqual(conditioning, (bundle / "ltx-quality-audio.wav").resolve())
            with wave.open(str(conditioning)) as wav:
                padded = wav.readframes(wav.getnframes())
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(padded[:len(pcm)], pcm)
                self.assertEqual(set(padded[len(pcm):]), {0})
                self.assertAlmostEqual(wav.getnframes() / 16000, details["duration"], delta=1/16000)
            metadata = json.loads((bundle / "render.json").read_text())
            self.assertEqual(metadata["seed"], 42)
            self.assertEqual(metadata["conditioning_audio_sha256"], hashlib.sha256(conditioning.read_bytes()).hexdigest())
            self.assertTrue((bundle / "output.mp4").is_file())
            self.assertEqual((bundle / "output.mp4").read_bytes(), final_video)
            self.assertEqual((bundle / "ltx-output.mp4").read_bytes(), native_video)
            self.assertEqual(metadata["lipsync"]["provider"], "musetalk-mac")
            self.assertEqual(metadata["lipsync"]["conditioning_audio_sha256"], metadata["conditioning_audio_sha256"])
            self.assertEqual((bundle / "ltx.log").read_text(), "rendered")

    def test_quality_frames_cover_audio_on_ltx_grid(self):
        frames, duration = talking_photo_ltx.quality_frames(3.0)
        self.assertEqual(frames, 73)
        self.assertAlmostEqual(duration, 73 / 24)
        self.assertGreaterEqual(duration, 3.0)
        self.assertEqual((frames - 1) % 8, 0)

    def test_quality_frames_accept_15_and_20_second_audio(self):
        for seconds, frames_expected in ((10.01, 241), (15.0, 361), (20.0, 481)):
            with self.subTest(seconds=seconds):
                frames, duration = talking_photo_ltx.quality_frames(seconds)
                self.assertEqual(frames, frames_expected)
                self.assertGreaterEqual(duration, seconds)
                self.assertEqual((frames - 1) % 8, 0)

    def test_quality_frames_reject_audio_above_20_seconds(self):
        with self.assertRaisesRegex(RuntimeError, "maximal 20 Sekunden"):
            talking_photo_ltx.quality_frames(20.0001)

    def test_target_dimensions_are_conservative_and_orientation_aware(self):
        self.assertEqual(talking_photo_ltx.target_dimensions(900, 1400), (512, 704))
        self.assertEqual(talking_photo_ltx.target_dimensions(1400, 900), (704, 512))
        self.assertEqual(talking_photo_ltx.target_dimensions(1000, 1000), (640, 640))

    def test_provider_health_requires_runtime_runner_and_model(self):
        fake_python = mock.Mock()
        fake_python.is_file.return_value = True
        fake_runner = mock.Mock()
        fake_runner.is_file.return_value = True
        fake_model = mock.Mock()
        fake_model.is_dir.return_value = True
        embedded = mock.Mock()
        embedded.is_file.return_value = True
        fake_model.__truediv__ = mock.Mock(return_value=embedded)

        with mock.patch.object(talking_photo_ltx, "RUNTIME_PYTHON", fake_python), \
             mock.patch.object(talking_photo_ltx, "RUNNER", fake_runner), \
             mock.patch.object(talking_photo_ltx, "MODEL_DIR", fake_model), \
             mock.patch("agent.talking_photo_ltx.os.access", return_value=True):
            health = talking_photo_ltx.provider_health()

        self.assertTrue(health["ready"])
        self.assertEqual(health["provider"], "ltx-2.5-mlx-a2v")
        self.assertEqual(health["max_audio_seconds"], 20.0)


if __name__ == "__main__":
    unittest.main()
