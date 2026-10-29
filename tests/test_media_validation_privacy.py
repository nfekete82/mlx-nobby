"""Image validation failures must never retain uploads/validator inputs in chat."""
import io
import json
import urllib.error
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent import app as agent, image_api, media_queue, video_api
from backend.video_errors import INVALID_VIDEO
from backend import app as web
from backend.media_errors import INVALID_IMAGE_REQUEST
from backend.media_errors import image_validation_message
from image_service import Generate


PRIVATE = [{"type": "value_error", "msg": "Traceback /Users/private/source.png",
            "input": {"source_path": "/private/uploads/source.png", "metadata": "private upload metadata"}}]


def test_known_public_model_and_job_id_errors_remain_precise():
    for value in ["Ungültige Image-Job-ID", "Ungültige Image-Modell-ID"]:
        assert image_validation_message(value) == value
    assert image_validation_message("/private/uploads/secret.png") == INVALID_IMAGE_REQUEST


@pytest.mark.parametrize("status", [400, 422])
@pytest.mark.parametrize("boundary", ["queue", "image_api", "web_image", "web_chat"])
def test_image_validation_is_sanitized_at_every_boundary(status, boundary):
    error = urllib.error.HTTPError("http://local/test", status, "invalid", {}, io.BytesIO(json.dumps({"detail": PRIVATE}).encode()))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises((HTTPException, media_queue.ServiceError)) as caught:
            if boundary == "queue":
                media_queue._service_request("image", "POST", "/jobs", {})
            elif boundary == "image_api":
                image_api._raw_request("POST", "/generate", {})
            elif boundary == "web_image":
                web.agent_json_request("POST", "/api/image/jobs", {})
            else:
                web.agent_json_request("POST", "/api/chat/actions", {"resolved_target": "image"})
    assert caught.value.detail == INVALID_IMAGE_REQUEST


@pytest.mark.parametrize("error_kind", ["http", "pydantic"])
def test_image_chat_tool_envelope_is_public_even_with_http_200(error_kind):
    error = HTTPException(422, PRIVATE)
    if error_kind == "pydantic":
        try:
            Generate.model_validate({"prompt": PRIVATE})
        except ValidationError as exc:
            error = exc
    with mock.patch.object(agent, "_start_chat_image_job", side_effect=error):
        result = agent.run_chat_action(agent.ChatActionRequest(
            prompt="Erstelle ein Bild von einer roten Kugel", resolved_target="image"))
    assert result["status"] == "failed"
    assert result["error"] == INVALID_IMAGE_REQUEST
    assert result["data"]["error_code"] == "image_validation_error"


@pytest.mark.parametrize("payload", [{"resolved_target": "image", "action": []},
                                     {"resolved_target": [], "action": "image_generate"}])
def test_malformed_action_shape_keeps_422_and_public_error(payload):
    error = urllib.error.HTTPError("http://local/test", 422, "invalid", {}, io.BytesIO(json.dumps({"detail": PRIVATE}).encode()))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(HTTPException) as caught:
            web.agent_json_request("POST", "/api/chat/actions", payload)
    assert caught.value.status_code == 422
    assert caught.value.detail == INVALID_IMAGE_REQUEST


@pytest.mark.parametrize("body", [b'[]', b'"private upload path"', b'<html>Traceback /private/source</html>'])
@pytest.mark.parametrize("bridge,expected", [(image_api, INVALID_IMAGE_REQUEST), (video_api, INVALID_VIDEO)])
def test_malformed_native_error_envelope_keeps_status_and_hides_body(body, bridge, expected):
    error = urllib.error.HTTPError("http://local/test", 422, "invalid", {}, io.BytesIO(body))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(HTTPException) as caught:
            bridge._raw_request("POST", "/generate", {})
    assert caught.value.status_code == 422
    assert caught.value.detail == expected
