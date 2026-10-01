"""Compatibility helpers; portrait policy lives in media_intent."""
from backend.media_intent import decide_media_intent


def _portrait_topic(prompt):
    return any(term in str(prompt).casefold() for term in ("porträt", "portrait", "headshot"))


def is_instructional_portrait_question(prompt):
    return is_portrait_chat_question(prompt) and any(
        term in str(prompt).casefold() for term in ("wie", "how", "way", "erklär")
    )


def is_portrait_chat_question(prompt):
    return _portrait_topic(prompt) and decide_media_intent(prompt).intent == "discussion"


def is_explicit_portrait_generation(prompt):
    return _portrait_topic(prompt) and decide_media_intent(prompt).intent == "image_generate"


def install_runtime():
    """Retained for entrypoint compatibility; no monkey-patched regex guards."""
