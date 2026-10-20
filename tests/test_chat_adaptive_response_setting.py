"""Keep adaptive response-length setting per chat without changing legacy chats."""
from agent import app as agent_app


def chat_with_setting(value, *, include=True):
    settings = {
        "system_prompt": "A custom roleplay persona.",
        "preset_id": "custom",
        "temperature": 0.9,
        "max_tokens": 6000,
    }
    if include:
        settings["adaptive_response_length"] = value
    return {
        "id": "test-adaptive-response-01",
        "title": "Roleplay",
        "created": 1,
        "updated": 2,
        "messages": [],
        "settings": settings,
    }


def test_adaptive_opt_in_survives_normalization():
    normalized = agent_app.normalize_chat(chat_with_setting(True))
    assert normalized["settings"]["adaptive_response_length"] is True


def test_adaptive_off_and_legacy_without_key_stay_off():
    disabled = agent_app.normalize_chat(chat_with_setting(False))
    assert disabled["settings"]["adaptive_response_length"] is False
    legacy = agent_app.normalize_chat(chat_with_setting(None, include=False))
    assert "adaptive_response_length" not in legacy["settings"]


def test_adaptive_rejects_non_boolean_values():
    for invalid in ("true", 1, None, [], {}):
        assert agent_app.normalize_chat(chat_with_setting(invalid)) is None
