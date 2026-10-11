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
    r"(?:die\s+|das\s+|alle\s+|all\s+|our\s+)?"
    r"(?:gesamte\s+|gesamten\s+|entire\s+)?"
    r"(?:neuen?\s+|current\s+)?"
    r"(?:modelle|models|produkte|products|geräte|devices|lineup|"
    r"portfolio|sortiment|modellreihe|serie|series|smartphones|phones)"
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
        # Do not cut in the middle of a sentence, especially not before a
        # caveat such as 'not yet on sale'. Keep a complete source line.
        if end < len(text):
            boundary = text.rfind("\n", start + _MIN_TEXT, end)
            if boundary < 0:
                continue
            end = boundary
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


_LINEUP_STATUSES = re.compile(
    r"(?i)\b(?:sortiment|modellsortiment|modellpalette|modellauswahl|"
    r"modellübersicht|angebot|lineup|catalog|catalogue|"
    r"(?:aktuell\s+)?(?:erhältlich|verfügbar|available)|"
    r"vorbestellbar|bestellbar|"
    r"(?:zum|jetzt)\s+(?:kauf|kaufen|bestellen|buy|purchase)|"
    r"(?:zum\s+verkauf|for\s+sale))\b"
)
# Verbs such as "bietet/offers" also describe *features* (e.g. a camera).
# They only signal catalog status if the named manufacturer is the subject.
_MODEL_TOPICS = ("iphone", "ipad", "macbook", "airpods", "galaxy",
                 "surface", "pixel", "watch", "laptop", "tablet", "smartphone")


def catalog_claim_is_lineup(goal, claim):
    """Reject off-topic features for a question asking WHICH products are offered.

    This is only a *relevance* filter. Anchored evidence and model entailment
    still establish whether a relevant statement is supported by sources.
    """
    if not official_catalog_goal(goal):
        return True
    statement = str(getattr(claim, "statement", "") or "")
    if not _LINEUP_STATUSES.search(statement):
        from agent.plan_fastpath import _brand_for_goal
        brand = _brand_for_goal(goal)
        if not brand or not re.search(
            r"(?i)\b" + re.escape(brand) +
            r"\s+(?:(?:offiziell|aktuell)\s+)?(?:bietet|verkauft|führt|listet|offers|sells|lists)\b",
            statement,
        ):
            return False
    names = " ".join(str(getattr(claim, k, "") or "")
                     for k in ("subject", "value", "statement")).lower()
    goal_lower = str(goal).lower()
    topics = [t for t in _MODEL_TOPICS if re.search(
        r"(?<!\w)" + re.escape(t) + r"(?!\w)", goal_lower)]
    if not topics:
        # A general multi-family manufacturer catalog may lack a shared model
        # prefix. The verifier must still establish exact product identities.
        return True
    return any(re.search(r"(?<!\w)" + re.escape(topic) + r"\s+[\w-]+", names)
               for topic in topics)
