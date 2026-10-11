"""Conservative source-anchored contradiction for announced regional sale dates.

Only a narrow explicit claim form and exact regional launch sentences qualify.
Missing or ambiguous provenance is not itself proof of a contradiction.
"""
from datetime import date, datetime, timezone
import re

_DATE = re.compile(r"(?<!\d)20\d\d-\d\d-\d\d(?!\d)")
_STARTED = re.compile(
    r"^\s*(?P<product>[\w][\w .+&/()'-]{1,75}?)\s+sales\s+"
    r"(?:have|has)\s+(?:already\s+)?(?:begun|started)\s+in\s+"
    r"(?P<region>[A-Za-z][A-Za-z -]{1,48})[.!?]?\s*$", re.I,
)


def _regional_launch_clauses(region):
    region_pattern = r"\s+".join(map(re.escape, region.split()))
    verb = r"(?:will\s+)?(?:begin|start)s?"
    return re.compile(
        rf"\b(?:in\s+{region_pattern}\s*,?\s+sales\s+{verb}|"
        rf"sales\s+{verb}\s+in\s+{region_pattern}|"
        rf"sales\s+in\s+{region_pattern}\s+{verb})\b", re.I,
    )


def future_regional_sale_start_conflicts(statement, passages, *, as_of=None):
    """Return matching passage IDs only for unambiguous future sale starts.

    passages: iterable of (validated source passage ID, exact source excerpt).
    A same-region start on or before the cutoff, or an ambiguous date, causes
    an abstention. This is not a general semantic truth verifier.
    """
    claim = _STARTED.fullmatch(str(statement or ""))
    if not claim:
        return []
    if as_of is None:
        cutoff = datetime.now(timezone.utc).date()
    elif isinstance(as_of, datetime):
        cutoff = as_of.date()
    elif isinstance(as_of, date):
        cutoff = as_of
    else:
        try:
            cutoff = date.fromisoformat(str(as_of))
        except ValueError:
            return []

    product = claim.group("product").strip()
    region = claim.group("region").strip()
    product_re = re.compile(r"(?<!\w)" + re.escape(product) + r"(?!\w)", re.I)
    regional_event = _regional_launch_clauses(region)
    future = []
    for passage_id, excerpt in passages:
        if not isinstance(passage_id, str) or not isinstance(excerpt, str):
            continue
        if not product_re.search(excerpt):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", excerpt):
            event = regional_event.search(sentence)
            if event is None:
                continue
            rest = sentence[event.end():]
            dates = list(_DATE.finditer(rest))
            # Reject mixed dates, hedged events, or text without an explicit
            # "on/from DATE" relationship to the regional sales start.
            if len(dates) != 1 or not re.fullmatch(
                r"\s*(?:on|from)\s+", rest[:dates[0].start()], re.I
            ):
                return []
            try:
                start = date.fromisoformat(dates[0].group())
            except ValueError:
                return []
            if start <= cutoff:
                return []
            future.append(passage_id)
    return list(dict.fromkeys(future))
