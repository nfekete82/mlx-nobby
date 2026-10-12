"""Fail-closed check for incompatible annual-leave units and workweek sizes.

A statute's nominal Werktage total must not be presented as the count of
Arbeitstage for a shorter workweek. This is a consistency veto, NOT a fact
generator: it cannot assert any corrected amount or replace original evidence.
"""
import re

_FIVE_DAY = re.compile(
    r"(?i)(?:fünf|fuenf|5)[-\s]*(?:tage|tages)[-\s]*woche|"
    r"(?:5|fünf|fuenf)\s*(?:arbeits)?tage\s*(?:pro|je|in\s+der)\s*woche"
)
_LEAVE = re.compile(r"(?i)mindesturlaub|urlaubstage|urlaubsanspruch|gesetzlich.{0,30}urlaub")
_NOMINAL = re.compile(r"(?i)\b24\s+werktage\b")
_24_DAYS = re.compile(
    r"(?i)\b24\s*(?:gesetzliche\s+)?(?:urlaubs|arbeits|werk)?tage\b|"
    r"\b24\s+(?:werktage|arbeitstage|urlaubstage)\b"
)
_STATUTE = re.compile(
    r"(?i)(?:urlaub\s+beträgt\s+jährlich\s+mindestens\s+24\s+werktage|"
    r"§\s*3.{0,100}24\s+werktage|"
    r"mindestens\s+24\s+werktage)"
)


def incompatible_leave_workweek(goal, statement, source_passages):
    """Return True only for the known mismatched statute unit and workweek.

    For any claim with insufficient context, return False and let the normal
    semantic verifier decide. A veto cannot manufacture positive evidence.
    """
    if not (_FIVE_DAY.search(str(goal or "")) and
            _LEAVE.search(str(goal or "")) and
            _24_DAYS.search(str(statement or ""))):
        return False
    if not source_passages or not any(
        isinstance(p, str) and _STATUTE.search(p)
        for p in source_passages
    ):
        return False
    return True
