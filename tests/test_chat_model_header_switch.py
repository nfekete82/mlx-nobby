"""Header chat model switch must update the active runtime and ONLY chat role."""
from unittest import mock
import pytest
from fastapi import HTTPException

from agent import app as agent_app
from backend import app as web_app


@pytest.fixture
def model_roles():
    return {
        "chat": "qwen38",
        "agent": "qwen38",
        "coding": "coding42",
        "vision": "vision3",
        "vision_uncensored": "uncensoredv",
        "embedding": "embed",
        "image": "image",
    }


def test_chat_header_switch_preserves_other_model_roles(model_roles):
    saved = []
    with mock.patch.object(agent_app, "load_models",
                           return_value=[{"alias": "dark-scarlett-27b",
                                          "repo": "user/Dark-Scarlett"}]), \
         mock.patch.object(agent_app, "switch_model_runtime",
                           return_value={"runtime": {"repo": "user/Dark-Scarlett"}}) as switch, \
         mock.patch.object(agent_app, "load_model_roles", return_value=model_roles), \
         mock.patch.object(agent_app, "save_model_roles",
                           side_effect=lambda roles: saved.append(dict(roles)) or dict(roles)):
        result = agent_app.select_chat_model("dark-scarlett-27b")

    assert result["ok"] is True
    assert result["scope"] == "chat"
    assert result["alias"] == "dark-scarlett-27b"
    switch.assert_called_once_with("dark-scarlett-27b")
    assert len(saved) == 1
    assert saved[0]["chat"] == "dark-scarlett-27b"
    assert all(saved[0][key] == value
               for key, value in model_roles.items() if key != "chat")


def test_chat_header_switch_fails_closed_if_model_unknown_or_restart_fails(model_roles):
    with mock.patch.object(agent_app, "load_models", return_value=[]), \
         mock.patch.object(agent_app, "switch_model_runtime") as switch:
        with pytest.raises(HTTPException) as exc:
            agent_app.select_chat_model("invented-model")
        assert exc.value.status_code == 404
        switch.assert_not_called()

    with mock.patch.object(agent_app, "load_models",
                           return_value=[{"alias": "dark", "repo": "owner/dark"}]), \
         mock.patch.object(agent_app, "switch_model_runtime",
                           side_effect=RuntimeError("Model load blocked")), \
         mock.patch.object(agent_app, "save_model_roles") as save:
        with pytest.raises(HTTPException) as exc:
            agent_app.select_chat_model("dark")
        assert exc.value.status_code == 503
        save.assert_not_called()


def test_chat_header_switch_refuses_busy_runtime():
    lock = mock.Mock()
    lock.acquire.return_value = False
    with mock.patch.object(agent_app, "MODEL_RUNTIME_LOCK", lock), \
         mock.patch.object(agent_app, "switch_model_runtime") as switch:
        with pytest.raises(HTTPException) as exc:
            agent_app.select_chat_model("dark")
        assert exc.value.status_code == 409
        switch.assert_not_called()
        lock.release.assert_not_called()


def test_web_header_proxy_is_chat_only():
    with mock.patch.object(web_app, "post_json", return_value={"ok": True}) as post:
        assert web_app.mlx_chat_model("dark-scarlett-27b") == {"ok": True}
    post.assert_called_once_with(
        web_app.AGENT_URL + "/api/model/chat/dark-scarlett-27b",
        timeout=300,
    )
