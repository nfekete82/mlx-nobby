"""Conservative, deterministic precision-edit assistance for Qwen 2.1.

This is *not* image segmentation or visual recognition. It only chooses an
unambiguous text target for MFLUX's existing --auto-mask segmenter, and
returns non-semantic pixel-change statistics after the edit. Never claim
that image identity, intent compliance or unchanged areas are guaranteed.
"""
from __future__ import annotations

import re
from pathlib import Path

# Deliberately small allowlist: adding objects needs test images and evaluation.
_TARGETS = {
    "sweater": r"pullover|sweater|hoodie",
    "shirt": r"hemd|t[- ]?shirt|shirt|bluse",
    "jacket": r"jacke|jacket|coat|mantel",
    "dress": r"kleid|dress",
    "pants": r"hose|hosen|pants|trousers|jeans",
    "shoes": r"schuhe|schuh|shoes|sneakers",
    "hair": r"haare|haar|hair",
    "sky": r"himmel|sky",
    "wall": r"wand|mauer|wall",
    "door": r"tür|tuer|door",
    "car": r"auto|wagen|car",
}
_ACTION = re.compile(
    r"\b(?:mach(?:e|st|en)?|änder(?:e|n|t)?|aender(?:e|n|t)?|"
    r"färb(?:e|en|t)?|faerb(?:e|en|t)?|ersetze|ersetz|"
    r"bearbeite|edit|change|make|recolor|replace|turn|color|colour)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(
    r"\b(?:nicht|kein(?:e|en|em|er|es)?|ohne|unverändert|unveraendert|"
    r"don't|do not|keep|preserve|unchanged|without)\b",
    re.IGNORECASE,
)
_CONTRAST = re.compile(r"[,;.!?]|\s+\b(?:aber|jedoch|but|except|while|sonst)\b", re.IGNORECASE)


def infer_auto_mask_target(prompt: str | None) -> str | None:
    """Return exactly one positive, obvious object target, else no mask.

    Keeps broad/ambiguous requests on the existing unmasked edit pathway.
    A target string alone never proves that the actual segmentation is right.
    """
    if not isinstance(prompt, str) or not 3 <= len(prompt) <= 2000:
        return None
    positive_clause = _CONTRAST.split(prompt.strip(), maxsplit=1)[0]
    if _NEGATED.search(positive_clause) or not _ACTION.search(positive_clause):
        return None
    matched = [
        target for target, pattern in _TARGETS.items()
        if re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", positive_clause, re.IGNORECASE)
    ]
    return matched[0] if len(matched) == 1 else None


def original_image_id(path: Path, output: Path) -> str | None:
    """Expose source through existing authenticated images endpoint only."""
    resolved = path.resolve()
    if resolved.parent != output.resolve():
        return None
    match = re.fullmatch(r"(\d{9,12}-[a-f0-9]{12})\.png", resolved.name)
    return match.group(1) if match and resolved.is_file() else None


def image_change_advisory(source: Path, edited: Path) -> dict | None:
    """Low-cost aggregate visual-change telemetry, not a quality verdict.

    Percent of 256px sampled image pixels with >= 12/255 max-channel change.
    No original image bytes, prompt, segmentation or private paths are returned.
    """
    from PIL import Image, ImageChops, ImageStat

    try:
        with Image.open(source) as first, Image.open(edited) as second:
            old = first.convert("RGB")
            new = second.convert("RGB")
            if old.size != new.size:
                return {"status": "unverified", "reason": "dimensions_differ"}
            old.thumbnail((256, 256), Image.Resampling.LANCZOS)
            new = new.resize(old.size, Image.Resampling.LANCZOS)
        diff = ImageChops.difference(old, new)
        # Each pixel counts once, regardless of the number of changed channels.
        changed = sum(
            max(rgb) >= 12 for rgb in diff.getdata()
        )
        fraction = round(changed / (old.width * old.height), 4)
        # Purely mechanical smoke tests: cannot assert semantic preservation.
        status = "review" if fraction < .001 or fraction > .995 else "unverified"
        return {"status": status, "changed_fraction": fraction}
    except (OSError, ValueError):
        return {"status": "unverified", "reason": "comparison_unavailable"}
