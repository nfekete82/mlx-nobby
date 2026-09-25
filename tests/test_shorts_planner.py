import json
from unittest import mock

import pytest
from pydantic import ValidationError

from agent.model_provider import ModelResponse
from agent.shorts_planner import ShortPlanningError, ShortProject, plan_short


def response(value):
    return ModelResponse(
        text=value,
        model="local/model",
        role="agent",
        usage={},
    )


def valid_plan(**changes):
    value = {
        "title": "Berlin in zehn Jahren",
        "duration": 20,
        "aspect_ratio": "9:16",
        "language": "de",
        "voice_enabled": True,
        "music_enabled": False,
        "subtitles_enabled": True,
        "scenes": [
            {
                "id": f"scene-{index}",
                "duration": 5,
                "narration": f"Szene {index}",
                "video_prompt": f"Berlin future scene {index}",
            }
            for index in range(1, 5)
        ],
    }
    value.update(changes)
    return value


def test_valid_20_second_short_uses_four_five_second_scenes():
    provider = mock.Mock()
    provider.complete.return_value = response(json.dumps(valid_plan()))

    project = plan_short(
        "Erstelle mir ein 20-sekündiges Short über Berlin in 10 Jahren",
        provider,
    )

    assert project.duration == 20
    assert [scene.duration for scene in project.scenes] == [5, 5, 5, 5]
    assert provider.complete.call_count == 1


def test_short_defaults_are_vertical_and_german():
    payload = valid_plan()
    payload.pop("aspect_ratio")
    payload.pop("language")

    project = ShortProject.model_validate(payload)

    assert project.aspect_ratio == "9:16"
    assert project.language == "de"


def test_invalid_scene_duration_is_rejected():
    payload = valid_plan()
    payload["scenes"][0]["duration"] = 7

    with pytest.raises(ValidationError, match="scene duration must be one of"):
        ShortProject.model_validate(payload)


def test_scene_durations_must_equal_project_duration():
    with pytest.raises(ValidationError, match="sum exactly"):
        ShortProject.model_validate(valid_plan(duration=25))


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ShortProject.model_validate(valid_plan(unexpected=True))

    payload = valid_plan()
    payload["scenes"][0]["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ShortProject.model_validate(payload)


@pytest.mark.parametrize("field", ["narration", "video_prompt"])
def test_scene_text_must_not_be_empty(field):
    payload = valid_plan()
    payload["scenes"][0][field] = "   "

    with pytest.raises(ValidationError, match="at least 1 character"):
        ShortProject.model_validate(payload)


def test_broken_json_gets_exactly_one_repair_attempt():
    provider = mock.Mock()
    provider.complete.side_effect = [
        response('{"title":'),
        response(json.dumps(valid_plan())),
    ]

    project = plan_short("Ein Short über Berlin", provider)

    assert project.title == "Berlin in zehn Jahren"
    assert provider.complete.call_count == 2
    repair_request = provider.complete.call_args_list[1].args[0]
    assert repair_request.temperature == 0.0
    assert "Return JSON only" in repair_request.messages[0]["content"]


def test_broken_json_after_repair_fails():
    provider = mock.Mock()
    provider.complete.side_effect = [
        response("not json"),
        response("still not json"),
    ]

    with pytest.raises(ShortPlanningError, match="after one repair attempt"):
        plan_short("Ein Short über Berlin", provider)

    assert provider.complete.call_count == 2
