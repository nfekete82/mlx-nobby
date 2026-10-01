"""Keep explicit portrait-generation requests on the image route.

The Agent already recognizes natural portrait requests such as
"Erstelle ein fotorealistisches Porträt ...". The web routing guard has its
own conservative explicit-image detector, so extend that detector with the
same portrait vocabulary instead of letting the confidence fallback demote a
confirmed image route back to chat.
"""

from __future__ import annotations

import importlib
import re


_PORTRAIT_IMAGE_REQUEST = re.compile(
    r"(?:\b(?:"
    r"erstelle|erstell|erstellen|erzeugen|erzeuge|generiere|generieren|"
    r"zeichne|zeichnen|male|malen|mache|mach|render(?:e|n)?|"
    r"create|generate|draw|paint|make|render"
    r")\b[\s\S]{0,140}?\b(?:porträt|portrait|headshot)\b)"
    r"|(?:\b(?:porträt|portrait|headshot)\b[\s\S]{0,140}?\b(?:"
    r"erstellen|erzeuge|erzeugen|generiere|generieren|zeichnen|malen|"
    r"machen|rendern|create|generate|draw|paint|make|render"
    r")\b)"
    r"|(?:\b(?:porträt|portrait|headshot)\s+(?:von|of)\b)",
    re.IGNORECASE,
)


def is_explicit_portrait_generation(prompt):
    """Return True only for clear portrait creation instructions."""
    return bool(
        _PORTRAIT_IMAGE_REQUEST.search(
            str(prompt or "").strip()
        )
    )


def install_runtime():
    """Extend the routing guard's existing explicit-image regex in place."""
    routing = importlib.import_module("backend.media_routing_ui")

    if getattr(routing, "_mlx_portrait_image_guard_v1", False):
        return routing._EXPLICIT_IMAGE_REQUEST

    original = routing._EXPLICIT_IMAGE_REQUEST
    routing._EXPLICIT_IMAGE_REQUEST = re.compile(
        rf"(?:{original.pattern})|(?:{_PORTRAIT_IMAGE_REQUEST.pattern})",
        original.flags | re.IGNORECASE,
    )
    routing._mlx_portrait_image_guard_v1 = True
    return routing._EXPLICIT_IMAGE_REQUEST
