"""Deterministic routing helpers for local vision models.

This module deliberately contains no model-loading code. Content
classification and model execution stay separate so classifiers can be
replaced without changing the vision runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


DEFAULT_VISION_ROLE = "vision"
UNCENSORED_VISION_ROLE = "vision_uncensored"


SAFE_LABELS = frozenset({
    "safe",
    "sfw",
    "suggestive",
    "nudity_nonsexual",
})

ADULT_LABELS = frozenset({
    "nsfw",
    "adult",
    "adult_nudity",
    "adult_explicit",
    "explicit",
})

AMBIGUOUS_LABELS = frozenset({
    "ambiguous",
    "unknown",
    "age_ambiguous",
})


@dataclass(frozen=True)
class VisionClassification:
    label: str
    confidence: float = 0.0
    scores: Mapping[str, float] | None = None

    def __post_init__(self):
        normalized = str(self.label or "").strip().lower()

        if not normalized:
            normalized = "unknown"

        confidence = float(self.confidence)

        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("Vision classification confidence must be between 0 and 1")

        object.__setattr__(self, "label", normalized)
        object.__setattr__(self, "confidence", confidence)


def select_vision_role(
    classification: VisionClassification | None,
    *,
    uncensored_role_available: bool = True,
    uncensored_min_confidence: float = 0.60,
) -> str:
    """Choose the logical model role for image understanding.

    MLX Nobby prefers the uncensored-capable VLM for every multimodal turn
    whenever that role is available. Safety classification remains useful
    metadata for diagnostics and observability, but it no longer decides
    which VLM handles the request.

    ``classification`` and ``uncensored_min_confidence`` stay in the public
    signature for compatibility with existing callers and telemetry.
    """

    _ = classification, uncensored_min_confidence

    if uncensored_role_available:
        return UNCENSORED_VISION_ROLE

    return DEFAULT_VISION_ROLE
