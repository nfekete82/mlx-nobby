"""Keep explicit portrait-generation requests on the image route.

The Agent already recognizes natural portrait requests such as
"Erstelle ein fotorealistisches Porträt ...". The web routing guard has its
own conservative explicit-image detector, so extend that detector with the
same portrait vocabulary while keeping instructional and discussion questions
on the normal chat/vision route.
"""

from __future__ import annotations

import importlib
import re


_CREATE_VERB = (
    r"(?:erstelle|erstell|erstellen|erzeug(?:e|en)?|generier(?:e|en)?|"
    r"zeichne|zeichnen|male|malen|mache|mach|machen|render(?:e|n)?|"
    r"create|generate|draw|paint|make|render)"
)
_PORTRAIT_TERM = (
    r"(?:porträtfotografie|portraitfotografie|portrait\s+photography|"
    r"porträt|portrait|headshot)"
)

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

_PORTRAIT_DISCUSSION_LEAD = re.compile(
    r"^\s*(?:"
    r"was\s+(?:hältst\s+du|haeltst\s+du|denkst\s+du|meinst\s+du|ist|sind)\b"
    r"|wie\s+(?:findest\s+du|gefällt|gefaellt|wirkt|ist|sind)\b"
    r"|(?:ist|sind)\b"
    r"|(?:bewert(?:e|en)?|beurteil(?:e|en)?|analysier(?:e|en)?|vergleich(?:e|en)?)\b"
    r"|what\s+(?:do\s+you\s+think|is|are)\b"
    r"|how\s+(?:do\s+you\s+like|does|is|are)\b"
    r"|(?:is|are|review|evaluate|analy[sz]e|compare)\b"
    r")",
    re.IGNORECASE,
)


def _mentions_portrait_topic(prompt):
    return bool(re.search(rf"\b{_PORTRAIT_TERM}\b", str(prompt or ""), re.IGNORECASE))


def is_instructional_portrait_question(prompt):
    """Return True for portrait how-to/explanation questions, not generation jobs."""
    text = str(prompt or "").strip()
    if not text or not _INSTRUCTIONAL_LEAD.search(text):
        return False
    return bool(
        _mentions_portrait_topic(text)
        and re.search(rf"\b{_CREATE_VERB}\b", text, re.IGNORECASE)
    )


def is_portrait_chat_question(prompt):
    """Recognize questions/discussion about portrait imagery as chat/vision.

    This deliberately does not catch direct generation requests such as
    "Kannst du ein Porträt erstellen?". How-to questions remain chat even when
    they contain a creation verb.
    """
    text = str(prompt or "").strip()
    if not text or not _mentions_portrait_topic(text):
        return False
    if is_instructional_portrait_question(text):
        return True
    if not _PORTRAIT_DISCUSSION_LEAD.search(text):
        return False
    return not bool(_PORTRAIT_IMAGE_REQUEST.search(text))


def is_explicit_portrait_generation(prompt):
    """Return True only for clear portrait creation instructions."""
    text = str(prompt or "").strip()
    if is_portrait_chat_question(text):
        return False
    return bool(_PORTRAIT_IMAGE_REQUEST.search(text))


def install_runtime():
    """Extend image intent while protecting portrait questions/discussion."""
    routing = importlib.import_module("backend.media_routing_ui")

    if getattr(routing, "_mlx_portrait_image_guard_v3", False):
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
        if target == "image" and is_portrait_chat_question(prompt):
            return False
        return original_explicit_intent(prompt, target, action)

    def conservative_media_target(prompt, target):
        if target == "image" and is_portrait_chat_question(prompt):
            return "chat"
        return original_conservative_media_target(prompt, target)

    def guard_reason(prompt, original_target, conservative_target):
        if (
            original_target == "image"
            and conservative_target == "chat"
            and is_portrait_chat_question(prompt)
        ):
            if is_instructional_portrait_question(prompt):
                return "instructional_portrait_question"
            return "portrait_chat_question"
        return original_guard_reason(prompt, original_target, conservative_target)

    routing._explicit_intent = explicit_intent
    routing.conservative_media_target = conservative_media_target
    routing._guard_reason = guard_reason
    routing._mlx_portrait_image_guard_v3 = True
    return routing._EXPLICIT_IMAGE_REQUEST
