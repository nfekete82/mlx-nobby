import pytest
from pydantic import ValidationError

from agent import shorts_jobs
from agent.shorts_planner import ShortProject, _planning_messages


def project(**changes):
    value = {
        "title": "Berlin in zehn Jahren",
        "duration": 20,
        "music_enabled": False,
        "scenes": [
            {
                "id": f"scene-{index}",
                "duration": 5,
                "narration": f"Szene {index}",
                "video_prompt": f"Future Berlin scene {index}",
            }
            for index in range(1, 5)
        ],
    }
    value.update(changes)
    return ShortProject.model_validate(value)


def test_voice_defaults_preserve_existing_speech_service_behavior():
    value = project()

    assert value.voice is None
    assert value.voice_speed == 1.0
    assert shorts_jobs.tts_payload_for_project(value) == {
        "input": "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4",
        "language": "de",
    }


def test_explicit_voice_and_speed_are_forwarded_to_tts():
    value = project(voice="Pervin", voice_speed=1.1)

    assert shorts_jobs.tts_payload_for_project(value) == {
        "input": "Szene 1\n\nSzene 2\n\nSzene 3\n\nSzene 4",
        "language": "de",
        "voice": "Pervin",
        "speed": 1.1,
    }

    metadata = shorts_jobs._tts_metadata(
        value,
        shorts_jobs.narration_for_project(value),
    )
    assert metadata["voice"] == "Pervin"
    assert metadata["speed"] == 1.1


def test_voice_name_and_speed_are_bounded():
    with pytest.raises(ValidationError):
        project(voice="../../outside")

    with pytest.raises(ValidationError):
        project(voice_speed=0.49)

    with pytest.raises(ValidationError):
        project(voice_speed=2.01)


def test_planner_does_not_invent_voice_configuration():
    system = _planning_messages("Ein Short über Berlin")[0]["content"]

    assert "leave voice null" in system
    assert "Never invent a voice name" in system
