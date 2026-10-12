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
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6,
    "july": 7, "october": 10, "december": 12,
}
MONTH = "|".join(MONTHS)
DATES = re.compile(
    rf"(?<!\d)(?:(\d{{1,2}})\.(\d{{1,2}})\.(20\d{{2}})|"
    rf"(\d{{1,2}})\.?\s+({MONTH})\s+(20\d{{2}})|"
    rf"(20\d{{2}})-(\d{{2}})-(\d{{2}})|"
    rf"({MONTH})\s+(\d{{1,2}}),?\s+(20\d{{2}}))(?!\d)",
    re.I,
)
SINCE = re.compile(r"\b(?:seit\s+(?:dem\s+)?|since\s+)$", re.I)
CURRENT = re.compile(r"\b(?:(?:bereits|jetzt|sofort|aktuell)\s+(?:erhältlich|verfügbar|lieferbar)|(?:already|currently|now)\s+(?:available|on sale))\b", re.I)
FUTURE_EVENT = re.compile(r"\b(?:erhältlich\s+ab|verfügbar\s+ab|verkaufsstart|marktstart|available\s+(?:from|on)|on sale\s+(?:from|on))\b", re.I)


def _date(match):
    try:
        if match.group(1):
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if match.group(4):
            return date(int(match.group(6)), MONTHS[match.group(5).lower()], int(match.group(4)))
        if match.group(7):
            return date(int(match.group(7)), int(match.group(8)), int(match.group(9)))
        return date(int(match.group(12)), MONTHS[match.group(10).lower()], int(match.group(11)))
    except (ValueError, KeyError):
        return None


def future_availability_conflicts(answer, today=None):
    today = today or date.today()
    issues = []
    for line in str(answer or "").splitlines():
        matches = list(DATES.finditer(line))
        current = any(not re.search(r"\b(?:nicht|not)\s*$", line[:m.start()], re.I)
                      for m in CURRENT.finditer(line))
        for index, match in enumerate(matches):
            target = _date(match)
            if target is None or target <= today:
                continue
            prefix = line[matches[index - 1].end() if index else 0:match.start()]
            # Match the closest nearby availability wording; unrelated dates
            # in earlier paragraphs must not trigger a warning.
            since = bool(SINCE.search(prefix[-24:]))
            if since or (current and FUTURE_EVENT.search(prefix[-80:])):
                issues.append({"line": line.strip()[:300], "date": target.isoformat()})
    return issues


def gate_temporal_claims(answer, today=None):
    issues = future_availability_conflicts(answer, today)
    if not issues:
        return answer
    dates = ", ".join(dict.fromkeys(item["date"] for item in issues))
    warning = (
        "**Zeitprüfung:** Eine Aussage über bereits erfolgte Verfügbarkeit "
        + f"oder einen vergangenen Start widerspricht einem zukünftigen Datum ({dates}). "
        + "Der Produktstatus muss überprüft werden."
    )
    return answer if warning in str(answer) else str(answer).rstrip() + "\n\n" + warning
