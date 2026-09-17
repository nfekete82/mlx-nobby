"""Deterministic routing helpers for local vision models.

This module deliberately contains no model-loading code.  Content
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
    """Choose the logical model role for a classified image.

    Adult content is routed only when the classifier is sufficiently
    confident. Unknown or ambiguous classifications deliberately use the
    normal vision role.
    """

    if classification is None:
        return DEFAULT_VISION_ROLE

    if (
        uncensored_role_available
        and classification.label in ADULT_LABELS
        and classification.confidence >= uncensored_min_confidence
    ):
        return UNCENSORED_VISION_ROLE

    return DEFAULT_VISION_ROLE
