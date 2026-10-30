"""No MLX weights needed: protect original Qwen TTS instead of LTX audio."""
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agent.talking_photo_audio_mux import preserve_speech


def test_original_tts_replaces_generated_ltx_track(tmp_path):
    source_video = b"\x00\x00\x00\x18ftyp" + b"V" * 96
    speech_wav = b"RIFF" + b"G" * 100
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["video"] = Path(command[command.index("-i") + 1]).read_bytes()
        captured["speech"] = Path(command[command.index("-i", command.index("-i") + 1) + 1]).read_bytes()
        Path(command[-1]).write_bytes(b"\x00\x00\x00\x18ftyp" + b"OUTPUT" * 12)
        return SimpleNamespace(returncode=0, stderr="")

    with mock.patch("agent.talking_photo_audio_mux.shutil.which", return_value="/usr/bin/ffmpeg"), \
         mock.patch("agent.talking_photo_audio_mux.subprocess.run", side_effect=fake_run):
        result = preserve_speech(source_video, speech_wav, tmp_path)

    cmd = captured["command"]
    assert captured["video"] == source_video
    assert captured["speech"] == speech_wav
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "1:a:0"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert result.startswith(b"\x00\x00\x00\x18ftyp")
    assert not list(tmp_path.glob("*"))


def test_audio_mux_fails_closed_without_ffmpeg(tmp_path):
    with mock.patch("agent.talking_photo_audio_mux.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg fehlt"):
            preserve_speech(b"video", b"speech", tmp_path)
