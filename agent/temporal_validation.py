"""Conservative warnings for internally contradictory availability dates.

This checker does not establish release truth. It only flags dated claims of
past/current availability when the same assertion refers to a future date.
"""
import re
from datetime import date

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3,
    "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
MONTH = "|".join(MONTHS)
DATES = re.compile(
    rf"(?<!\d)(?:(\d{{1,2}})\.(\d{{1,2}})\.(20\d{{2}})|"
    rf"(\d{{1,2}})\.\s*({MONTH})\s+(20\d{{2}}))(?!\d)",
    re.I,
)
SINCE = re.compile(r"\bseit\s+(?:dem\s+)?$", re.I)
CURRENT = re.compile(r"\b(?:bereits|jetzt|sofort|aktuell)\s+erhältlich\b", re.I)
FUTURE_EVENT = re.compile(r"\b(?:erhältlich\s+ab|verfügbar\s+ab|verkaufsstart|marktstart)\b", re.I)


def _date(match):
    try:
        if match.group(1):
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        return date(int(match.group(6)), MONTHS[match.group(5).lower()], int(match.group(4)))
    except (ValueError, KeyError):
        return None


def future_availability_conflicts(answer, today=None):
    today = today or date.today()
    issues = []
    for line in str(answer or "").splitlines():
        matches = list(DATES.finditer(line))
        current_and_future = bool(CURRENT.search(line) and FUTURE_EVENT.search(line))
        for match in matches:
            target = _date(match)
            if target is None or target <= today:
                continue
            prefix = line[:match.start()]
            # Match the closest nearby availability wording; unrelated dates
            # in earlier paragraphs must not trigger a warning.
            since = bool(SINCE.search(prefix[-24:]))
            if since or current_and_future:
                issues.append({"line": line.strip()[:300], "date": target.isoformat()})
    return issues


def gate_temporal_claims(answer, today=None):
    if "**Zeitprüfung:**" in str(answer):
        return answer
    issues = future_availability_conflicts(answer, today)
    if not issues:
        return answer
    dates = ", ".join(dict.fromkeys(item["date"] for item in issues))
    return (
        str(answer).rstrip()
        + "\n\n**Zeitprüfung:** Eine Aussage über bereits erfolgte Verfügbarkeit "
        + f"oder einen vergangenen Start widerspricht einem zukünftigen Datum ({dates}). "
        + "Der Produktstatus muss überprüft werden."
    )
