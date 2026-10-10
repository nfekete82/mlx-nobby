"""Narrow deterministic fixes for explicit future availability contradictions.

No assertion about external release truth: the correction only reconciles dates
that are already present in the answer with the local calendar date.
"""
import re
from datetime import date
from agent.temporal_validation import DATES, _date

SINCE_DATE = re.compile(
    r"(?i)\bseit\s+(?:dem\s+)?(?=\d{1,2}\.)"
)
PRESENT = re.compile(r"(?i)\b(?:bereits|jetzt|sofort|aktuell)\s+erhältlich\b")
FUTURE = re.compile(r"(?i)\b(?:erhältlich|verfügbar)\s+ab\b")


def correct_future_availability(answer, today=None):
    """Repair only lines with an unambiguous dated contradiction."""
    if not isinstance(answer, str):
        return answer
    today = today or date.today()
    corrected = []
    for line in answer.splitlines(keepends=True):
        matches = [m for m in DATES.finditer(line)
                   if (value := _date(m)) is not None and value > today]
        if not matches:
            corrected.append(line)
            continue
        # Correct 'seit <future date>' only when the date immediately follows.
        for match in reversed(matches):
            prefix = line[:match.start()]
            since = re.search(r"(?i)\bseit\s+(?:dem\s+)?$", prefix)
            if since:
                line = line[:since.start()] + "laut genanntem Termin erst ab " + line[match.start():]
        # For an explicit current/future contradiction, replace the present
        # availability claim; preserve the source's future date unchanged.
        if FUTURE.search(line) and PRESENT.search(line):
            line = PRESENT.sub("laut genanntem Termin noch nicht erhältlich", line, count=1)
        corrected.append(line)
    return "".join(corrected)
