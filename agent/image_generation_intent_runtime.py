"""Extend deterministic image-generation intent detection for portrait prompts.

The browser asks the Agent for a semantic preflight target before it opens the
media-quality picker. Natural prompts such as "Erstelle ein fotorealistisches
Porträt ..." do not contain the legacy Bild/Foto nouns, so make that common
image intent deterministic without changing the broader semantic router.
"""

from __future__ import annotations

from functools import wraps
import importlib
import re


_CREATION_VERB_PATTERN = re.compile(
    r"\b(?:"
    r"erstelle|erstellen|generiere|generieren|erzeuge|erzeugen|"
    r"zeichne|zeichnen|mach|mache|create|generate|draw|make"
    r")\b",
    re.IGNORECASE,
)
_PORTRAIT_NOUN_PATTERN = re.compile(
    r"\b(?:porträt|portrait|headshot)\b",
    re.IGNORECASE,
)
_PORTRAIT_OF_PATTERN = re.compile(
    r"\b(?:porträt|portrait|headshot)\s+(?:von|of)\b",
    re.IGNORECASE,
)


def is_portrait_generation_request(prompt):
    value = str(prompt or "").strip()
    if not value:
        return False

    return bool(
        _PORTRAIT_OF_PATTERN.search(value)
        or (
            _CREATION_VERB_PATTERN.search(value)
            and _PORTRAIT_NOUN_PATTERN.search(value)
        )
    )


def install_runtime():
    """Patch the Agent's existing deterministic image-intent extension point."""
    agent_app = importlib.import_module("agent.app")
    original = agent_app._looks_like_image_generation_request

    if getattr(original, "__mlx_portrait_intent_v1__", False):
        return original

    @wraps(original)
    def wrapped(prompt):
        return original(prompt) or is_portrait_generation_request(prompt)

    wrapped.__mlx_portrait_intent_v1__ = True
    agent_app._looks_like_image_generation_request = wrapped
    return wrapped
