"""Conservative effective-date consistency checks for dated claims.

Never infer the date of a policy or financial change from a decision date.
Only a single explicit "effective from" date in the actually loaded source
can contradict a claimed "since" date. Ambiguous source dates abstain.
"""
import re
from agent.temporal_validation import DATES, _date

_EFFECTIVE = re.compile(
    r"(?i)\b(?:with effect from|effective (?:from|on)|takes effect (?:from|on)|"
    r"in effect since|gilt (?:ab|seit(?: dem)?)|wirksam (?:ab|seit(?: dem)?)|"
    r"gültig (?:ab|seit(?: dem)?))\s*:?\s*"
)
_CLAIM_SINCE = re.compile(
    r"(?i)\b(?:seit(?: dem)?|gilt (?:ab|seit)|gültig (?:ab|seit)|"
    r"wirksam (?:ab|seit)|effective (?:from|since|on)|takes effect (?:on|from)|"
    r"applies (?:from|since))\b"
)


def effective_date_conflict(statement, source_texts):
    """Return one explicit mismatch; None never means that a claim is proven."""
    if not _CLAIM_SINCE.search(str(statement or "")):
        return None
    claim_dates = {_date(m) for m in DATES.finditer(str(statement))}
    claim_dates.discard(None)
    if len(claim_dates) != 1:
        return None
    actual_dates = set()
    for source in source_texts:
        if not isinstance(source, str):
            continue
        for marker in _EFFECTIVE.finditer(source):
            # The effective date must immediately follow its own semantic cue.
            nearby = source[marker.end():marker.end() + 48]
            match = DATES.search(nearby)
            if match is None or match.start() > 8:
                continue
            date = _date(match)
            if date is not None:
                actual_dates.add(date)
    if len(actual_dates) != 1:
        return None
    claimed, actual = next(iter(claim_dates)), next(iter(actual_dates))
    if claimed == actual:
        return None
    return {"claimed_date": claimed.isoformat(),
            "source_effective_date": actual.isoformat()}
