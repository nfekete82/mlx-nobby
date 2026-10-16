"""Selected speaker steering for LTX Distilled and LTX Direct.

This validates prompt routing and unchanged input images without running the large model.
It does not assert visual speaker identity, which requires a real video acceptance test.
"""
import io
import json
import math
from contextlib import nullcontext
from pathlib import Path
import subprocess
import tempfile
import wave
from unittest import mock

import pytest
from pydantic import ValidationError

from agent import talking_photo_ltx, talking_photo_person_focus
from agent.talking_photo_routes import TalkingPhotoRequest


def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(12800))
    return buf.getvalue()


def test_standard_prompt_is_identical_without_selection():
    assert talking_photo_ltx.speaker_prompt(None) == talking_photo_ltx.TALKING_PROMPT


@pytest.mark.parametrize("x,chosen,listener", [
    (0.0, "left", "right"),
    (0.49, "left", "right"),
    (0.5, "right", "left"),
    (1.0, "right", "left"),
])
def test_selected_speaker_prompt_preserves_both_people(x, chosen, listener):
    prompt = talking_photo_ltx.speaker_prompt({"x": x, "y": 0.4})
    assert f"person on the {chosen} side" in prompt
    assert f"on the {listener}" in prompt
    assert "ONLY speaker" in prompt
    assert "silent listener" in prompt
    assert "BOTH people" in prompt
    assert "natural blinking" in prompt


@pytest.mark.parametrize("value", [
    {"x": -0.1, "y": 0.5},
    {"x": 0.2, "y": 1.1},
    {"x": float("nan"), "y": 0.5},
    {"x": float("inf"), "y": 0.5},
    {"x": True, "y": 0.5},
    {"x": 0.2},
    {"x": 0.2, "y": 0.4, "extra": 1},
])
def test_bad_positions_are_rejected(value):
    with pytest.raises(ValueError):
        talking_photo_person_focus.validate_focus(value)


def test_api_schema_accepts_ltx_focus_and_rejects_out_of_range():
    common = {"image_data_url": "data:image/png;base64,AAAA", "text": "Hallo"}
    request = TalkingPhotoRequest.model_validate({
        **common,
        "engine": "ltx-distilled",
        "person_focus": {"x": 0.2, "y": 0.4},
    })
    assert request.model_dump()["person_focus"] == {"x": 0.2, "y": 0.4}
    with pytest.raises(ValidationError):
        TalkingPhotoRequest.model_validate({
            **common,
            "person_focus": {"x": float("nan"), "y": 0.4},
        })


@pytest.mark.parametrize("distilled", [False, True])
def test_ltx_runner_uses_selected_prompt_and_unchanged_full_image(distilled):
    native_mp4 = bytes(4) + b"ftyp" + bytes(48)
    original_image = b"original-photo-bytes"
    commands = []
    real_popen = subprocess.Popen

    def fake_popen(command, **kwargs):
        if "--output" not in command:
            return real_popen(command, **kwargs)
        commands.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(native_mp4)
        process = mock.Mock(returncode=0)
        process.communicate.return_value = ("ok", None)
        return process

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        with (
            mock.patch.object(talking_photo_ltx, "provider_health", return_value={"ready": True}),
            mock.patch.object(talking_photo_ltx, "_image_size", return_value=(640, 512)),
            mock.patch.object(talking_photo_ltx.runtime_coordinator, "video_runtime", return_value=nullcontext()),
            mock.patch.object(talking_photo_ltx.subprocess, "Popen", side_effect=fake_popen),
        ):
            mp4, metadata = talking_photo_ltx.generate(
                "f" * 24, original_image, ".png", wav_bytes(), 0.4, root,
                cancelled=lambda: False, distilled=distilled,
                person_focus={"x": 0.23, "y": 0.4},
            )
        cmd = commands[0]
        assert mp4 == native_mp4
        assert Path(cmd[cmd.index("--image") + 1]).read_bytes() == original_image
        assert "person on the left side" in cmd[cmd.index("--prompt") + 1]
        assert cmd[cmd.index("--mode") + 1] == ("distilled" if distilled else "classic")
        assert metadata["person_focus"] == {"x": 0.23, "y": 0.4}
        assert metadata["speaker_selection"] == "prompt-guided"
        assert metadata["prompt"] == cmd[cmd.index("--prompt") + 1]
