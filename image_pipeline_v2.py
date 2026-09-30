"""Deterministic, content-safe routing helpers for Image Pipeline V2.

The router classifies image-generation intent without retaining prompts.  It
returns only coarse intent/reason metadata and an ordered model candidate list.
"""

from __future__ import annotations

import re

import image_registry as registry


_PATTERN_FLAGS = re.IGNORECASE

FAST_PATTERN = re.compile(
    r"\b(?:fast|quick|preview|draft|schnell|vorschau|entwurf)\b",
    _PATTERN_FLAGS,
)
TEXT_LAYOUT_PATTERN = re.compile(
    r"\b(?:poster|typography|text|lettering|logo|ui|interface|schrift|"
    r"typografie|beschriftung|headline|slogan|label|packaging|verpackung)\b",
    _PATTERN_FLAGS,
)
PHOTO_PATTERN = re.compile(
    r"\b(?:photo|photograph|photographic|photorealistic|photo-realistic|"
    r"realistic(?:\s+photo)?|camera|dslr|fotograf(?:ie|isch)?|foto|"
    r"fotorealistisch|realistisch(?:es\s+foto)?)\b",
    _PATTERN_FLAGS,
)
PERSON_PATTERN = re.compile(
    r"\b(?:portrait|porträt|headshot|person|people|human|menschen?|woman|"
    r"women|man|men|frau|frauen|mann|männer|fashion|modefoto|model)\b",
    _PATTERN_FLAGS,
)
PRODUCT_PATTERN = re.compile(
    r"\b(?:product|produkt|packshot|shoe|schuh|car|auto|vehicle|fahrzeug|"
    r"bottle|flasche|watch|uhr|phone|smartphone|device|gerät)\b",
    _PATTERN_FLAGS,
)
ILLUSTRATION_PATTERN = re.compile(
    r"\b(?:illustration|illustrated|drawing|sketch|painting|anime|manga|"
    r"comic|cartoon|zeichnung|gemälde|malerei)\b",
    _PATTERN_FLAGS,
)
COMPLEX_PATTERN = re.compile(
    r"\b(?:complex\s+prompt|high\s+prompt\s+fidelity|prompt\s+fidelity|"
    r"komplexer\s+prompt|hohe\s+prompttreue)\b",
    _PATTERN_FLAGS,
)


def _unique(values):
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def classify_image_intent(prompt):
    """Return a coarse image intent and non-sensitive routing signals."""
    value = str(prompt or "").strip()
    lowered = value.lower()

    signals = {
        "fast": bool(FAST_PATTERN.search(lowered)),
        "text_layout": bool(TEXT_LAYOUT_PATTERN.search(lowered)),
        "photo": bool(PHOTO_PATTERN.search(lowered)),
        "person": bool(PERSON_PATTERN.search(lowered)),
        "product": bool(PRODUCT_PATTERN.search(lowered)),
        "illustration": bool(ILLUSTRATION_PATTERN.search(lowered)),
        "complex": bool(COMPLEX_PATTERN.search(lowered)) or len(value) >= 320,
    }

    if signals["fast"]:
        intent = "fast_draft"
        reason = "fast-request"
    elif signals["text_layout"]:
        intent = "text_layout"
        reason = "text-or-layout"
    elif signals["person"] and (signals["photo"] or not signals["illustration"]):
        # Portrait/headshot language is a strong enough signal for the local
        # photoreal SDXL model even when the user omits the word "photo".
        intent = "photoreal_person"
        reason = "person-photo"
    elif signals["product"] and signals["photo"]:
        intent = "product_photo"
        reason = "product-photo"
    elif signals["illustration"]:
        intent = "illustration"
        reason = "illustration-style"
    elif signals["complex"]:
        intent = "complex_prompt"
        reason = "prompt-fidelity"
    else:
        intent = "generic"
        reason = "default"

    return {
        "intent": intent,
        "reason": reason,
        "signals": signals,
    }


def routing_candidates(intent, default_model=None):
    """Return model ids in priority order for one classified image intent."""
    mapping = {
        "fast_draft": [
            registry.Z_IMAGE_TURBO_ID,
            registry.MLXSERVE_QWEN_IMAGE21_ID,
        ],
        "text_layout": [
            registry.MLXSERVE_QWEN_IMAGE21_ID,
        ],
        "photoreal_person": [
            registry.JUGGERNAUT_XL_ID,
            registry.MLXSERVE_QWEN_IMAGE21_ID,
        ],
        "product_photo": [
            registry.MLXSERVE_QWEN_IMAGE21_ID,
            registry.JUGGERNAUT_XL_ID,
        ],
        "illustration": [
            registry.MLXSERVE_QWEN_IMAGE21_ID,
        ],
        "complex_prompt": [
            registry.MLXSERVE_QWEN_IMAGE21_ID,
        ],
        "generic": [],
    }
    return _unique([
        *mapping.get(str(intent or "generic"), []),
        default_model,
        registry.MLXSERVE_QWEN_IMAGE21_ID,
        registry.JUGGERNAUT_XL_ID,
    ])


def route_plan(prompt, default_model=None):
    """Return safe route metadata; prompt text is intentionally omitted."""
    classification = classify_image_intent(prompt)
    return {
        "version": 2,
        "intent": classification["intent"],
        "reason": classification["reason"],
        "signals": classification["signals"],
        "candidates": routing_candidates(
            classification["intent"],
            default_model,
        ),
    }
