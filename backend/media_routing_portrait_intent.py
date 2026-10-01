"""Keep explicit portrait-generation requests on the image route.

The Agent already recognizes natural portrait requests such as
"Erstelle ein fotorealistisches Porträt ...". The web routing guard has its
own conservative explicit-image detector, so extend that detector with the
same portrait vocabulary while keeping instructional questions such as
"Wie erstelle ich ein Porträt?" on the normal chat route.
"""

from __future__ import annotations

import importlib
import re


_CREATE_VERB = (
    r"(?:erstelle|erstell|erstellen|erzeug(?:e|en)?|generier(?:e|en)?|"
    r"zeichne|zeichnen|male|malen|mache|mach|machen|render(?:e|n)?|"
    r"create|generate|draw|paint|make|render)"
)
_PORTRAIT_TERM = r"(?:porträt|portrait|headshot)"

_PORTRAIT_IMAGE_REQUEST = re.compile(
    rf"(?:\b{_CREATE_VERB}\b[\s\S]{{0,140}}?\b{_PORTRAIT_TERM}\b)"
    rf"|(?:\b{_PORTRAIT_TERM}\b[\s\S]{{0,140}}?\b{_CREATE_VERB}\b)"
    rf"|(?:\b{_PORTRAIT_TERM}\s+(?:von|of)\b)",
    re.IGNORECASE,
)

_INSTRUCTIONAL_LEAD = re.compile(
    r"^\s*(?:"
    r"(?:kannst\s+du|könntest\s+du|koenntest\s+du|can\s+you|could\s+you)"
    r"[\s\S]{0,50}?\b(?:erklär(?:e|en)?|erklaer(?:e|en)?|zeig(?:e|en)?|sag(?:e|en)?|"
    r"explain|show|tell)\b"
    r"|(?:erklär(?:e|en)?|erklaer(?:e|en)?|zeig(?:e|en)?|sag(?:e|en)?|"
    r"explain|show|tell)\b"
    r"|(?:wie|how)\b"
    r"|(?:was|what)\b[\s\S]{0,70}?\b(?:weg|methode|method|way)\b"
    r")",
    re.IGNORECASE,
)


def is_instructional_portrait_question(prompt):
    """Return True for portrait how-to/explanation questions, not generation jobs."""
    text = str(prompt or "").strip()
    if not text or not _INSTRUCTIONAL_LEAD.search(text):
        return False
    return bool(
        re.search(rf"\b{_PORTRAIT_TERM}\b", text, re.IGNORECASE)
        and re.search(rf"\b{_CREATE_VERB}\b", text, re.IGNORECASE)
    )


def is_explicit_portrait_generation(prompt):
    """Return True only for clear portrait creation instructions."""
    text = str(prompt or "").strip()
    if is_instructional_portrait_question(text):
        return False
    return bool(_PORTRAIT_IMAGE_REQUEST.search(text))


def install_runtime():
    """Extend image intent while protecting instructional portrait questions."""
    routing = importlib.import_module("backend.media_routing_ui")

    if getattr(routing, "_mlx_portrait_image_guard_v2", False):
        return routing._EXPLICIT_IMAGE_REQUEST

    original_regex = routing._EXPLICIT_IMAGE_REQUEST
    routing._EXPLICIT_IMAGE_REQUEST = re.compile(
        rf"(?:{original_regex.pattern})|(?:{_PORTRAIT_IMAGE_REQUEST.pattern})",
        original_regex.flags | re.IGNORECASE,
    )

    original_explicit_intent = routing._explicit_intent
    original_conservative_media_target = routing.conservative_media_target
    original_guard_reason = routing._guard_reason

    def explicit_intent(prompt, target, action=None):
        if target == "image" and is_instructional_portrait_question(prompt):
            return False
        return original_explicit_intent(prompt, target, action)

    def conservative_media_target(prompt, target):
        if target == "image" and is_instructional_portrait_question(prompt):
            return "chat"
        return original_conservative_media_target(prompt, target)

    def guard_reason(prompt, original_target, conservative_target):
        if (
            original_target == "image"
            and conservative_target == "chat"
            and is_instructional_portrait_question(prompt)
        ):
            return "instructional_portrait_question"
        return original_guard_reason(prompt, original_target, conservative_target)

    routing._explicit_intent = explicit_intent
    routing.conservative_media_target = conservative_media_target
    routing._guard_reason = guard_reason
    routing._mlx_portrait_image_guard_v2 = True
    return routing._EXPLICIT_IMAGE_REQUEST
