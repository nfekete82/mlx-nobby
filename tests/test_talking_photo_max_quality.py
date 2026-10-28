"""CPU-only coverage for Talking Photo's opt-in 30+3 max-quality path."""
from contextlib import nullcontext
import io
from pathlib import Path
import tempfile
from unittest import mock
import wave

import pytest

from agent import talking_photo_ltx, talking_photo_quality


def wav_bytes(seconds=0.4):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((5000).to_bytes(2, "little", signed=True) * int(seconds * 16000))
    return buffer.getvalue()


def padded_wav(source, target, duration):
    with wave.open(str(source), "rb") as wav:
        audio = wav.readframes(wav.getnframes())
    length = int(round(duration * 16000))
    audio = audio[:length * 2].ljust(length * 2, b"\0")
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(audio)


@pytest.mark.parametrize("distilled,steps,expected", [
    (True, None, 8),
    (False, None, 15),
    (False, 30, 30),
])
def test_max_quality_really_changes_ltx_renderer_steps(distilled, steps, expected):
    commands = []
    mp4 = b"\0\0\0\x18ftyp" + b"0" * 48

    def fake_popen(command, **kwargs):
        commands.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(mp4)
        process = mock.Mock(returncode=0)
        process.communicate.return_value = ("ok", None)
        return process

    with (
        tempfile.TemporaryDirectory() as directory,
        mock.patch.object(talking_photo_ltx, "provider_health", return_value={"ready": True}),
        mock.patch.object(talking_photo_ltx, "_image_size", return_value=(640, 640)),
        mock.patch.object(talking_photo_ltx, "_pad_audio", side_effect=padded_wav),
        mock.patch.object(talking_photo_ltx.runtime_coordinator, "video_runtime", return_value=nullcontext()),
        mock.patch.object(talking_photo_ltx.subprocess, "Popen", side_effect=fake_popen),
    ):
        video, info = talking_photo_ltx.generate(
            "a" * 24, b"portrait", ".png", wav_bytes(), 0.4, Path(directory),
            cancelled=lambda: False, distilled=distilled, stage1_steps=steps,
            debug_dir=None,
        )
    command = commands[0]
    assert video == mp4
    assert command[command.index("--stage1-steps") + 1] == str(expected)
    assert command[command.index("--stage2-steps") + 1] == "3"
    assert command[command.index("--mode") + 1] == ("distilled" if distilled else "classic")
    assert info["stage_1_steps"] == expected
    if expected == 30:
        assert "--cfg-scale" in command
        assert "--stg-scale" in command


@pytest.mark.parametrize("distilled,steps", [
    (True, 30), (False, 20), (False, -1), (False, 300),
])
def test_bad_step_combinations_rejected_before_loading_models(distilled, steps):
    with mock.patch.object(talking_photo_ltx, "provider_health") as health:
        with pytest.raises(ValueError, match="Qualitätsstufe"):
            talking_photo_ltx.generate(
                "a" * 24, b"portrait", ".png", wav_bytes(), 0.4, Path("/nonexistent"),
                cancelled=lambda: False, distilled=distilled, stage1_steps=steps,
            )
    health.assert_not_called()


def test_create_job_records_max_engine_and_only_passes_validated_steps():
    request = {
        "image_data_url": "data:image/png;base64," + "A" * 48,
        "text": "Hallo", "language": "de",
    }
    with (
        mock.patch.object(talking_photo_quality, "direct_provider_health", return_value={"ready": True}),
        mock.patch.object(talking_photo_quality.talking_photo, "decode_image_data_url", return_value=(b"image", ".png")),
        mock.patch.object(talking_photo_quality.talking_photo, "_write_job"),
        mock.patch.object(talking_photo_quality.threading, "Thread") as thread,
    ):
        job = talking_photo_quality.create_job(request, ltx_only=True, stage1_steps=30)
        assert job["engine"] == "ltx-max"
        assert job["stage_1_steps"] == 30
        assert job["stage_2_steps"] == 3
        thread.return_value.start.assert_called_once_with()
        passed = thread.call_args.kwargs["args"][3]
        assert passed["_stage1_steps"] == 30
        assert passed["_ltx_only"] is True
        assert passed["_distilled"] is False
        with pytest.raises(ValueError, match="Maximale Qualität"):
            talking_photo_quality.create_job(request, ltx_only=True, distilled=True, stage1_steps=30)
        with pytest.raises(ValueError, match="Maximale Qualität"):
            talking_photo_quality.create_job(request, stage1_steps=30)
        with pytest.raises(ValueError, match="Maximale Qualität"):
            talking_photo_quality.create_job(request, ltx_only=True, stage1_steps=45)


@pytest.mark.parametrize("longform", [False, True])
def test_max_quality_reaches_short_and_longform_jobs_with_metadata(longform, tmp_path):
    root = tmp_path / "state"
    original = wav_bytes()
    rendered = b"\0\0\0\x18ftyp" + b"0" * 48
    results = []

    def record_job(_id, **changes):
        results.append(changes)

    with (
        mock.patch.object(talking_photo_quality.talking_photo, "ROOT", root),
        mock.patch.object(talking_photo_quality.talking_photo, "OUTPUT", root / "videos"),
        mock.patch.object(talking_photo_quality, "AUDIO_DEBUG_ROOT", root / "audio-debug"),
        mock.patch.object(talking_photo_quality.talking_photo, "_update_job", side_effect=record_job),
        mock.patch.object(talking_photo_quality.talking_photo, "_cancelled", return_value=False),
        mock.patch.object(talking_photo_quality.talking_photo, "_request_tts", return_value=b"speech"),
        mock.patch.object(talking_photo_quality.talking_photo, "_audio_to_wav", return_value=original),
        mock.patch.object(talking_photo_quality.talking_photo_ltx, "debug_directory", return_value=None),
        mock.patch.object(talking_photo_quality.talking_photo_motion, "wav_duration_seconds", return_value=25.0 if longform else 0.4),
        mock.patch.object(talking_photo_quality, "_generate_longform" if longform else "generate",
                          return_value=(rendered, {"stage_1_steps": 30, "a2v_mode": "classic"})) as render,
    ):
        talking_photo_quality._run_quality_job(
            "b" * 24, b"image", ".png", {
                "text": "Hallo", "language": "de", "speed": 1.0,
                "_ltx_only": True, "_distilled": False, "_stage1_steps": 30,
            },
        )
    assert render.call_args.kwargs["stage1_steps"] == 30
    completed = [c["result"] for c in results if c.get("status") == "completed"]
    assert len(completed) == 1
    assert completed[0]["engine"] == "ltx-max"
    assert completed[0]["stage_1_steps"] == 30
    assert completed[0]["stage_2_steps"] == 3


def test_generate_metadata_preserves_max_engine():
    details = {"a2v_mode": "classic", "stage_1_steps": 30}
    with mock.patch.object(talking_photo_quality.talking_photo_ltx, "generate",
                           return_value=(b"video", details)):
        result, metadata = talking_photo_quality.generate("abc", apply_lipsync=False)
    assert result == b"video"
    assert metadata["engine"] == "ltx-max"
