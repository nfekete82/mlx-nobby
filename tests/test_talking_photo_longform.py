"""Talking Photo 2.0: boundaries, cancellation and native MP4 assembly."""
from __future__ import annotations

from contextlib import nullcontext
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest import mock

from agent import talking_photo_longform, talking_photo_ltx, talking_photo_quality


def wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm)
    return buffer.getvalue()


def pcm_bytes(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav), "rb") as handle:
        return handle.readframes(handle.getnframes())


class TalkingPhotoLongformTests(unittest.TestCase):
    def test_short_audio_remains_single_segment(self):
        original = wav_bytes((3000).to_bytes(2, "little", signed=True) * 16000 * 10)
        chunks = talking_photo_longform.split_at_pauses(original)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(pcm_bytes(chunks[0].wav), pcm_bytes(original))
        self.assertEqual(chunks[0].video_frames, 240)

    def test_pause_based_chunks_reassemble_exact_original_samples(self):
        active = (6500).to_bytes(2, "little", signed=True)
        # Silence every ~13 seconds gives the planner preferable join points.
        source = wav_bytes(
            active * (12 * 16000) + bytes(16000) +
            active * (12 * 16000) + bytes(16000) +
            active * (12 * 16000) + bytes(16000)
        )
        parts = talking_photo_longform.split_at_pauses(source)
        self.assertGreaterEqual(len(parts), 3)
        self.assertLessEqual(len(parts), 6)
        self.assertEqual(b"".join(pcm_bytes(p.wav) for p in parts), pcm_bytes(source))
        self.assertEqual(sum(p.video_frames for p in parts), 900)
        self.assertTrue(all(p.duration_seconds <= 18.0 for p in parts))
        # Preferred boundaries must fall inside two of the actual 1-second pauses.
        borders = [p.end_sample / 16000 for p in parts[:-1]]
        self.assertTrue(any(12 <= x <= 13 for x in borders))
        self.assertTrue(any(24.5 <= x <= 25.0 for x in borders))

    def test_continuous_speech_uses_safe_low_energy_fallback(self):
        source = wav_bytes((5000).to_bytes(2, "little", signed=True) * (43 * 16000))
        parts = talking_photo_longform.split_at_pauses(source)
        self.assertGreaterEqual(len(parts), 3)
        self.assertEqual(b"".join(pcm_bytes(p.wav) for p in parts), pcm_bytes(source))
        self.assertTrue(all(0 < p.duration_seconds <= 18.0 for p in parts))

    def test_audio_over_60_seconds_fails_before_render(self):
        audio = wav_bytes((2500).to_bytes(2, "little", signed=True) * (61 * 16000))
        with self.assertRaisesRegex(RuntimeError, "maximal 60 Sekunden"):
            talking_photo_longform.split_at_pauses(audio)

    def test_chunk_render_calls_preserve_original_seed_and_initiate_single_assembly(self):
        audio = wav_bytes((3000).to_bytes(2, "little", signed=True) * (29 * 16000))
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fake_generate(job, image, image_suffix, segment_wav, duration, work, **kwargs):
                observed.append((job, segment_wav, duration, kwargs.get("distilled"), kwargs.get("apply_lipsync")))
                kwargs["update"](phase="quality", progress=.5)
                return bytes(4) + b"ftyp" + bytes(40), {"seed": 42, "elapsed_seconds": 1.0, "a2v_mode": "distilled"}
            def fake_assemble(original, segments, parts, work, **kwargs):
                self.assertEqual(original, audio)
                self.assertEqual(len(parts), len(segments))
                self.assertTrue(all(p.is_file() for p in parts))
                self.assertEqual(b"".join(pcm_bytes(s.wav) for s in segments), pcm_bytes(audio))
                return bytes(4) + b"ftyp" + bytes(50), {"audio_seconds":29.0,"source_audio_sha256":"test","segments":len(segments)}
            changes = []
            with mock.patch.object(talking_photo_quality, "generate", side_effect=fake_generate), \
                 mock.patch.object(talking_photo_longform, "assemble", side_effect=fake_assemble) as mux:
                video, diagnostics = talking_photo_quality._generate_longform(
                    "a" * 24, b"portrait", ".png", audio, root,
                    debug_dir=None, cancelled=lambda: False,
                    update=lambda **items: changes.append(items),
                    apply_lipsync=False, distilled=True,
                )
            self.assertGreaterEqual(len(observed), 2)
            self.assertTrue(all(x[0] == "a" * 24 and x[3] and x[4] is False for x in observed))
            self.assertEqual(mux.call_count, 1)
            self.assertTrue(video.startswith(bytes(4) + b"ftyp"))
            self.assertTrue(diagnostics["longform"])
            self.assertEqual(diagnostics["assembly"]["audio_seconds"], 29.0)
            self.assertEqual(len(diagnostics["chunks"]), len(observed))
            self.assertTrue(any(.2 < d.get("progress", 0) < .91 for d in changes))

    def test_cancellation_prevents_any_assembly_and_next_render(self):
        audio = wav_bytes((4500).to_bytes(2, "little", signed=True) * (30 * 16000))
        completed = [False]
        def fake_generate(*args, **kwargs):
            completed[0] = True
            return bytes(4) + b"ftyp" + bytes(40), {"a2v_mode": "distilled"}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(talking_photo_quality, "generate", side_effect=fake_generate) as render, \
                 mock.patch.object(talking_photo_longform, "assemble") as assemble:
                with self.assertRaises(talking_photo_ltx.QualityCancelled):
                    talking_photo_quality._generate_longform(
                        "b" * 24, b"portrait", ".png", audio, Path(directory),
                        debug_dir=None, cancelled=lambda: completed[0],
                        update=lambda **k: None, apply_lipsync=False, distilled=True,
                    )
                self.assertEqual(render.call_count, 1)
                assemble.assert_not_called()


    def test_next_segment_conditions_on_previous_visible_frame(self):
        from agent import talking_photo_continuity
        import os
        audio = wav_bytes((3000).to_bytes(2, "little", signed=True) * (30 * 16000))
        images = []
        continuation_png = talking_photo_continuity.PNG_HEADER + bytes(200)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fake_generate(job, image, suffix, segment_wav, duration, work, **kwargs):
                images.append((image, suffix))
                return bytes(4) + b"ftyp" + bytes(40), {
                    "seed": 42, "elapsed_seconds": 0.1, "a2v_mode": "distilled",
                }
            def fake_assemble(original, segments, parts, work, **kwargs):
                return bytes(4) + b"ftyp" + bytes(40), {
                    "audio_seconds": 30.0,
                    "source_audio_sha256": "test",
                    "segments": len(segments),
                }
            with mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_LONGFORM_CONTINUITY": "1"}), \
                 mock.patch.object(talking_photo_quality, "generate", side_effect=fake_generate), \
                 mock.patch.object(talking_photo_continuity, "extract_tail_frame",
                                   return_value=continuation_png) as extract, \
                 mock.patch.object(talking_photo_longform, "assemble",
                                   side_effect=fake_assemble):
                _video, details = talking_photo_quality._generate_longform(
                    "c" * 24, b"original portrait", ".jpg", audio, root,
                    debug_dir=None, cancelled=lambda: False, update=lambda **_: None,
                    apply_lipsync=False, distilled=True,
                )
            self.assertGreaterEqual(len(images), 2)
            self.assertEqual(images[0], (b"original portrait", ".jpg"))
            self.assertTrue(all(pair == (continuation_png, ".png") for pair in images[1:]))
            self.assertEqual(extract.call_count, len(images) - 1)
            self.assertEqual(details["continuity"]["applied"], len(images) - 1)
            self.assertEqual(details["continuity"]["fallbacks"], 0)
            self.assertEqual(details["chunks"][1]["reference"]["source"], "previous-content-frame")

    def test_failed_continuation_extraction_preserves_original_fallback(self):
        from agent import talking_photo_continuity
        import os
        audio = wav_bytes((2500).to_bytes(2, "little", signed=True) * (29 * 16000))
        images = []
        with tempfile.TemporaryDirectory() as directory:
            def fake_generate(job, image, suffix, *args, **kwargs):
                images.append((image, suffix))
                return bytes(4) + b"ftyp" + bytes(40), {"a2v_mode": "distilled"}
            with mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_LONGFORM_CONTINUITY": "1"}), \
                 mock.patch.object(talking_photo_quality, "generate", side_effect=fake_generate), \
                 mock.patch.object(talking_photo_continuity, "extract_tail_frame",
                                   side_effect=RuntimeError("ffmpeg decoding error")), \
                 mock.patch.object(talking_photo_longform, "assemble", return_value=(
                     b"video", {"audio_seconds": 29.0, "source_audio_sha256": "test"}
                 )):
                _, details = talking_photo_quality._generate_longform(
                    "d" * 24, b"source", ".png", audio, Path(directory),
                    debug_dir=None, cancelled=lambda: False, update=lambda **_: None,
                    apply_lipsync=False, distilled=True,
                )
            self.assertTrue(all(pair == (b"source", ".png") for pair in images))
            self.assertEqual(details["continuity"]["applied"], 0)
            self.assertEqual(details["continuity"]["fallbacks"], len(images) - 1)

    def test_continuity_is_disableable_without_touching_standard_pipeline(self):
        from agent import talking_photo_continuity
        import os
        with mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_LONGFORM_CONTINUITY": "0"}):
            self.assertFalse(talking_photo_continuity.enabled())
        with mock.patch.dict(os.environ, {"LTX_TALKING_PHOTO_LONGFORM_CONTINUITY": "1"}):
            self.assertTrue(talking_photo_continuity.enabled())

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires ffmpeg")
    def test_continuation_frame_extracts_exact_content_end_not_padding(self):
        from agent import talking_photo_continuity
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "two-colors.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=red:s=64x64:r=24:d=1",
                "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24:d=0.333333",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[vid]",
                "-map", "[vid]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(video),
            ], check=True, capture_output=True)
            data = talking_photo_continuity.extract_tail_frame(
                video, 24, root / "last-visible.png", cancelled=lambda: False,
            )
            with Image.open(io.BytesIO(data)) as frame:
                r, g, b = frame.convert("RGB").getpixel((32, 32))
            self.assertGreater(r, 160)
            self.assertLess(b, 90)
            self.assertLess(g, 90)

    def test_continuation_honors_cancellation(self):
        from agent import talking_photo_continuity
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "source.mp4"
            video.write_bytes(b"fake video")
            with self.assertRaises(talking_photo_ltx.QualityCancelled):
                talking_photo_continuity.extract_tail_frame(
                    video, 24, root / "reference.png", cancelled=lambda: True,
                )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg/ffprobe")
    def test_stitch_has_expected_frames_and_single_full_audio_track(self):
        samples = (4200).to_bytes(2, "little", signed=True) * 32000
        source = wav_bytes(samples)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = []
            for number, color in enumerate(("red", "blue")):
                video = root / f"part-{number}.mp4"
                subprocess.run([
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=c={color}:s=64x64:r=24:d=1",
                    "-frames:v", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(video),
                ], check=True, capture_output=True)
                videos.append(video)
            segments = [
                talking_photo_longform.AudioSegment(1, 0, 24, 0, 16000, wav_bytes(samples[:32000])),
                talking_photo_longform.AudioSegment(2, 24, 48, 16000, 32000, wav_bytes(samples[32000:])),
            ]
            video, details = talking_photo_longform.assemble(
                source, segments, videos, root / "assemble", cancelled=lambda: False,
            )
            self.assertTrue(video.startswith(bytes(4) + b"ftyp"))
            self.assertEqual(details["frames"], 48)
            self.assertAlmostEqual(details["audio_seconds"], 2.0)
            file = root / "final.mp4"
            file.write_bytes(video)
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,nb_frames",
                "-of", "json", str(file),
            ], check=True, capture_output=True, text=True)
            import json
            streams = json.loads(probe.stdout)["streams"]
            self.assertEqual([s["codec_type"] for s in streams].count("audio"), 1)
            self.assertEqual([s["codec_type"] for s in streams].count("video"), 1)
            self.assertEqual(int(next(s["nb_frames"] for s in streams if s["codec_type"] == "video")), 48)


if __name__ == "__main__":
    unittest.main()
