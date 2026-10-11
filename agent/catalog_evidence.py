"""Source-exact contextual excerpts for official product-catalog questions.

Short catalog cards often contain only a model name (too short for standard
sentence extraction). Preserve *contiguous original source text* from the
model overview; never construct lists by joining separate snippets.
These are passage candidates, not independently verified product availability.
"""
import re

from agent.plan_fastpath import official_catalog_goal


_SECTION = re.compile(
    r"(?i)(?:entdecke|entdecken|alle|unsere|vergleiche|vergleichen|"
    r"discover|explore|compare|shop|browse|our)\s+"
    r"(?:die\s+|alle\s+|all\s+|our\s+)?"
    r"(?:neuen?\s+|current\s+)?"
    r"(?:modelle|models|produkte|products|geräte|devices|lineup)"
)
_MIN_TEXT = 75
_WINDOW = 900


def catalog_source_windows(goal, text, *, max_windows=2):
    """Return up to two original-text offsets and exact source windows."""
    if not official_catalog_goal(goal) or not isinstance(text, str):
        return []
    windows = []
    for hit in _SECTION.finditer(text):
        start = hit.start()
        end = min(len(text), start + _WINDOW)
        # Keep a single short cohesive block rather than an arbitrarily
        # spliced set of product names from unrelated site sections.
        block = text[start:end]
        if len(block.strip()) < _MIN_TEXT:
            continue
        if any(abs(start - old_start) < _WINDOW for old_start, _, _ in windows):
            continue
        windows.append((start, end, block))
        if len(windows) >= max_windows:
            break
    return windows
