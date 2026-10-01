"""Compatibility API for the shared text-before-media policy."""
from backend.media_intent import decide_media_intent


def is_media_prompt_meta_request(prompt: str) -> bool:
    return decide_media_intent(prompt).intent == "prompt_writing"


def install_media_prompt_meta_guard() -> None:
    """Retained for entrypoint compatibility; policy no longer monkey-patches."""
