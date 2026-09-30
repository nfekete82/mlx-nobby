"""Keep prompt-writing/meta requests in chat instead of starting media jobs.

The model router occasionally classifies phrases such as "mach mir einen Prompt
für Juggernaut" as an image request.  This layer is deliberately applied before
the confidence guard: talking *about* a media prompt is a chat task even when
the router is highly confident.  A concrete execution instruction (for example
"generiere das Bild") still wins.
"""
from __future__ import annotations

import re

from backend import media_routing_ui as routing


_META_PROMPT_REQUEST = re.compile(
    r"(?:"
    r"\b(?:schreib(?:e|en)?|formulier(?:e|en)?|erstell(?:e|en)?|mach(?:e|en)?|"
    r"optimier(?:e|en)?|verbesser(?:e|n)?|überarbeit(?:e|en)?|ueberarbeit(?:e|en)?|"
    r"bau(?:e|en)?|gib|write|draft|compose|create|make|optimi[sz]e|improve|rewrite)\b"
    r"[\s\S]{0,100}?\b(?:negative[- ]?prompt|bildprompt|image[- ]?prompt|video[- ]?prompt|prompt)\b"
    r"|\b(?:negative[- ]?prompt|bildprompt|image[- ]?prompt|video[- ]?prompt|prompt)\b"
    r"[\s\S]{0,100}?\b(?:schreiben|formulieren|erstellen|machen|optimieren|verbessern|"
    r"überarbeiten|ueberarbeiten|write|draft|compose|create|make|optimi[sz]e|improve|rewrite)\b"
    r"|\b(?:welch(?:e|en|er|es)?|was\s+für\s+ein(?:en)?|was\s+fuer\s+ein(?:en)?|what|how)\b"
    r"[\s\S]{0,100}?\bprompt\b"
    r"|\bprompt\b[\s\S]{0,80}?\b(?:für|fuer|for)\b[\s\S]{0,80}?"
    r"\b(?:juggernaut(?:\s*xl)?|sdxl|stable\s+diffusion|flux|qwen(?:\s+image)?|mflux|"
    r"wan(?:\s*2(?:\.2)?)?|ltx(?:\s*2(?:\.5)?)?|bildmodell|image\s+model|videomodell|video\s+model)\b"
    r")",
    re.IGNORECASE,
)

# Deliberately narrower than the router's normal image/video intent regex.  It
# must not mistake "erstelle mir einen Prompt für das Bild" for an instruction
# to actually generate the image.
_EXPLICIT_MEDIA_EXECUTION = re.compile(
    r"(?:"
    r"\b(?:generiere|generier|erzeuge|render(?:e)?|generate|render)\b"
    r"[\s\S]{0,80}?\b(?:bild|foto|illustration|grafik|image|photo|picture|video|clip|animation)\b"
    r"|\b(?:erstelle|erstell|mach|mache|create|make)\b"
    r"(?:\s+(?:mir|bitte|jetzt|direkt|nun|nochmal|erneut))*\s+"
    r"(?:ein(?:e|en)?|das|dieses?|den)?\s*"
    r"\b(?:bild|foto|illustration|grafik|image|photo|picture|video|clip|animation)\b"
    r"|\b(?:nutze|verwende|nimm|use)\b[\s\S]{0,100}?\bprompt\b"
    r"[\s\S]{0,120}?\b(?:generiere|generier|erzeuge|render(?:e)?|generate|render)\b"
    r")",
    re.IGNORECASE,
)

_INSTALLED = False
_ORIGINAL_CONSERVATIVE = routing.conservative_media_target
_ORIGINAL_INTENT_NAME = routing._intent_name
_ORIGINAL_GUARD_REASON = routing._guard_reason


def is_media_prompt_meta_request(prompt: str) -> bool:
    """Return True when the user wants prompt text, not media execution."""
    text = str(prompt or "").strip()
    if not text or not _META_PROMPT_REQUEST.search(text):
        return False
    return not bool(_EXPLICIT_MEDIA_EXECUTION.search(text))


def _conservative_media_target(prompt: str, target: str) -> str:
    if target in routing.ACTIVE_MEDIA_TARGETS and is_media_prompt_meta_request(prompt):
        return "chat"
    return _ORIGINAL_CONSERVATIVE(prompt, target)


def _intent_name(prompt: str, target: str, action: str | None = None) -> str:
    if target in routing.ACTIVE_MEDIA_TARGETS and is_media_prompt_meta_request(prompt):
        return "media_prompt_meta"
    return _ORIGINAL_INTENT_NAME(prompt, target, action)


def _guard_reason(prompt: str, original_target: str, conservative_target: str) -> str | None:
    if (
        conservative_target == "chat"
        and original_target in routing.ACTIVE_MEDIA_TARGETS
        and is_media_prompt_meta_request(prompt)
    ):
        return "media_prompt_meta_chat"
    return _ORIGINAL_GUARD_REASON(prompt, original_target, conservative_target)


def install_media_prompt_meta_guard() -> None:
    """Install the routing override once for the production entrypoint."""
    global _INSTALLED
    if _INSTALLED:
        return
    routing.conservative_media_target = _conservative_media_target
    routing._intent_name = _intent_name
    routing._guard_reason = _guard_reason
    _INSTALLED = True
