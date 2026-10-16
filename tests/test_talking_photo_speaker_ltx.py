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
        wav.writeframes((5000).to_bytes(2, "little", signed=True) * 6400)
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
    common = {"image_data_url": "data:image/png;base64," + ("A" * 48), "text": "Hallo"}
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
    def fake_popen(command, **kwargs):
        assert "--output" in command
        commands.append(command)
        Path(command[command.index("--output") + 1]).write_bytes(native_mp4)
        process = mock.Mock(returncode=0)
        process.communicate.return_value = ("ok", None)
        return process

    def fake_pad_audio(source, target, duration):
        # This test checks LTX speaker prompt and the original image bytes,
        # not ffmpeg. Preserve valid, audible WAV data and exact padding length
        # without depending on ffmpeg availability on macOS CI runners.
        with wave.open(str(source), "rb") as wav:
            samples = wav.readframes(wav.getnframes())
        target_frames = math.ceil(duration * 16000)
        padding = max(0, target_frames - len(samples) // 2)
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples + bytes(padding * 2))

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        with (
            mock.patch.object(talking_photo_ltx, "provider_health", return_value={"ready": True}),
            mock.patch.object(talking_photo_ltx, "_image_size", return_value=(640, 512)),
            mock.patch.object(talking_photo_ltx, "_pad_audio", side_effect=fake_pad_audio),
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


def test_http_api_dispatches_selected_speaker_to_standard_ltx():
    """The selected point must reach the LTX job; it must not silently switch to Fast."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent import talking_photo_routes
    app = FastAPI()
    payload = {
        "image_data_url": "data:image/png;base64," + ("A" * 48),
        "text": "Hallo",
        "engine": "ltx-distilled",
        "person_focus": {"x": .18, "y": .45},
    }
    with (
        mock.patch.object(talking_photo_routes.talking_photo, "recover_jobs"),
        mock.patch.object(talking_photo_routes.talking_photo_quality, "create_job",
                          return_value={"id": "test", "status": "queued"}) as create,
        mock.patch.object(talking_photo_routes.talking_photo, "create_job") as fast,
    ):
        talking_photo_routes.install_routes(app)
        with TestClient(app) as client:
            response = client.post("/api/talking-photo/jobs", json=payload)
            assert response.status_code == 202, response.text
            payload_sent = create.call_args.args[0]
            assert payload_sent["person_focus"] == payload["person_focus"]
            assert create.call_args.kwargs == {"ltx_only": True, "distilled": True}
            fast.assert_not_called()
            response = client.post("/api/talking-photo/jobs", json={**payload, "engine": "quality"})
            assert response.status_code == 422
            assert create.call_count == 1
