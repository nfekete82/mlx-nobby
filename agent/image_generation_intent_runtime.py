"""Compatibility adapter for shared portrait intent; no independent policy."""
from functools import wraps
import importlib
from backend.media_intent import decide_media_intent


def is_portrait_generation_request(prompt):
    decision = decide_media_intent(prompt)
    return decision.intent == "image_generate" and any(
        term in str(prompt).casefold() for term in ("porträt", "portrait", "headshot")
    )


def install_runtime():
    agent_app = importlib.import_module("agent.app")
    original = agent_app._looks_like_image_generation_request
    if getattr(original, "__mlx_portrait_intent_v1__", False):
        return original

    @wraps(original)
    def wrapped(prompt):
        decision = decide_media_intent(prompt)
        if decision.intent in {"prompt_writing", "discussion"}:
            return False
        return original(prompt) or is_portrait_generation_request(prompt)

    wrapped.__mlx_portrait_intent_v1__ = True
    agent_app._looks_like_image_generation_request = wrapped
    return wrapped
