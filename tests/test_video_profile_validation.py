"""CPU-only profile/duration contract and privacy at all video service boundaries."""
import ast
import io
import json
from pathlib import Path
import urllib.error
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import video_long
import video_service as service
from agent import media_queue, video_api
from agent import app as agent
from backend import app as web
from backend.video_errors import INVALID_VIDEO, UNCENSORED_CONTINUATION, video_validation_message


@pytest.fixture(autouse=True)
def native_provider():
    with mock.patch.object(service.registry, "get_model", return_value={
        "id": "ltx-2.5-22b-distilled", "model_family": "ltx-2.5", "provider": "ltx-mlx",
    }), mock.patch.object(service, "validate_first_frame"), \
         mock.patch.object(service, "i2v_source_size", return_value=(1080, 1920)):
        yield


def request(operation, profile, duration, quality="quality"):
    return {"operation": operation, "chat_id": "profile-test", "chat_revision": 0,
            "payload": {"prompt": "A red ball rolls", "profile": profile, "quality": quality,
                        "duration": duration, "aspect_ratio": "9:16",
                        **({"first_frame": "/private/uploads/secret.png"} if operation == "i2v" else {})}}


@pytest.mark.parametrize("operation", ["t2v", "i2v"])
@pytest.mark.parametrize("profile", ["standard", "uncensored"])
@pytest.mark.parametrize("duration", [5, 10, 20])
@pytest.mark.parametrize("quality,direct_max", [("quality", 5), ("standard", 10), ("fast", 20)])
def test_profile_duration_matrix(operation, profile, duration, quality, direct_max):
    data = request(operation, profile, duration, quality)
    if profile == "uncensored" and duration > direct_max:
        with pytest.raises(ValidationError) as error:
            service.JobCreate.model_validate(data)
        assert error.value.errors()[0]["type"] == "uncensored_video_continuation_unsupported"
        return
    parsed = service.JobCreate.model_validate(data)
    assert parsed.payload.profile == profile
    assert parsed.payload.duration == duration
    assert parsed.payload.frames == duration * 24 + 1
    assert parsed.payload.aspect_ratio == "9:16"
    if quality == "quality":
        assert (parsed.payload.width, parsed.payload.height) == (1088, 1920)


def test_models_explicitly_advertises_no_uncensored_continuation():
    model = {"id": "test", "provider": "ltx-mlx"}
    with mock.patch.object(service.registry, "load_registry", return_value={"default_model": "test", "models": [model]}), \
         mock.patch.object(service.registry, "model_path", return_value=Path("/mock-model")), \
         mock.patch.object(service, "availability", return_value=(True, "mock")), \
         mock.patch.object(service, "_multi_capabilities", return_value={}), \
         mock.patch.object(service, "profile_capabilities", return_value={"uncensored_available": True}):
        profiles = service.models()["profiles"]
    assert profiles["uncensored_available"] is True
    assert profiles["uncensored_continuation_available"] is False
    assert profiles["uncensored_direct_max_seconds"] == {key: max(value) for key, value in video_long.DIRECT.items()}


def test_native_422_is_compact_german_without_input():
    client = TestClient(service.app, base_url="http://127.0.0.1")
    for endpoint in ["/preflight", "/jobs"]:
        response = client.post(endpoint, json=request("i2v", "uncensored", 10))
        assert response.status_code == 422
        assert response.json() == {"detail": UNCENSORED_CONTINUATION}
        invalid = request("i2v", "standard", 10)
        invalid["payload"]["duration"] = "private metadata"
        response = client.post(endpoint, json=invalid)
        assert response.status_code == 422
        assert response.json() == {"detail": INVALID_VIDEO}


PRIVATE_ERROR = [{"type": "value_error", "msg": "Traceback /Users/private/secret.png",
                  "input": {"first_frame": "/private/uploads/secret.png", "upload": "secret metadata"}}]


@pytest.mark.parametrize("detail,expected", [
    (PRIVATE_ERROR, INVALID_VIDEO), ("/Users/private/secret.png", INVALID_VIDEO),
    ({"code": {"untrusted": "code"}}, INVALID_VIDEO),
    ({"code": "video_profile_unavailable", "technical_detail": "secret"},
     "Das Profil „Uncensored“ ist nicht eingerichtet. Bitte Standard wählen."),
    ([{"type": "uncensored_video_continuation_unsupported", "input": "secret"}], UNCENSORED_CONTINUATION),
    (UNCENSORED_CONTINUATION, UNCENSORED_CONTINUATION),
])
def test_public_validation_allowlist(detail, expected):
    assert video_validation_message(detail) == expected


@pytest.mark.parametrize("boundary", ["queue", "agent", "web"])
@pytest.mark.parametrize("status", [400, 422])
def test_errors_are_sanitized_at_every_boundary(boundary, status):
    error = urllib.error.HTTPError("http://local/test", status, "invalid", {},
                                  io.BytesIO(json.dumps({"detail": PRIVATE_ERROR}).encode()))
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises((HTTPException, media_queue.ServiceError)) as caught:
            if boundary == "queue":
                media_queue._service_request("video", "POST", "/jobs", {})
            elif boundary == "agent":
                video_api._raw_request("POST", "/preflight", {})
            else:
                web.agent_json_request("POST", "/api/chat/actions", {"resolved_target": "video"})
    assert caught.value.detail == INVALID_VIDEO


def test_chat_tool_failure_is_sanitized_even_in_http_200_envelope():
    data = agent.ChatActionRequest(prompt="Erstelle ein Video von einem roten Ball",
                                   resolved_target="video", chat_id="test", chat_revision=0)
    with mock.patch.object(agent, "_start_chat_video_job", side_effect=HTTPException(422, PRIVATE_ERROR)):
        result = agent.run_chat_action(data)
    assert result["status"] == "failed"
    assert result["error"] == INVALID_VIDEO
    assert result["data"]["error_code"] == "video_validation_error"


def test_installed_extend_has_no_lora_contract_without_importing_mlx():
    cli = Path(__file__).resolve().parents[2] / ".local/share/mlx-nobby/ltx-2-mlx-v0.18.0/packages/ltx-pipelines-mlx/src/ltx_pipelines_mlx/cli.py"
    if not cli.is_file():
        pytest.skip("Pinned LTX-MLX checkout not installed on this test host")
    tree = ast.parse(cli.read_text())
    flags = {"ext": set(), "gen": set(), "parser": set()}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and isinstance(node.func.value, ast.Name)):
            name = node.func.value.id
            if name in flags:
                flags[name].update(arg.value for arg in node.args if isinstance(arg, ast.Constant))
    assert "--lora" in flags["gen"]
    assert "--lora" not in flags["ext"]
    base = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_add_base_args")
    assert "--lora" not in ast.unparse(base)
    for name in ["_cmd_extend", "_cmd_extend_distilled"]:
        handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert "_pending_loras" not in ast.unparse(handler)
