"""Conservative temporal status check for explicit future availability dates.

Requires both a concrete day/month/year and a current-availability assertion
in the same line. Only flags an inconsistency; does not infer launch facts.
"""
import re
from datetime import date, datetime

DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
AVAILABLE = re.compile(r"\b(?:bereits erhältlich|jetzt erhältlich|sofort erhältlich|seit heute erhältlich|aktuell erhältlich|currently available|available now)\b", re.I)
FUTURE_EVENT = re.compile(r"\b(?:erhältlich ab|verfügbar ab|verkaufsstart|marktstart|available from|on sale from)\b", re.I)


def future_availability_conflicts(answer, today=None):
    today = today or date.today()
    issues = []
    for line in str(answer or "").splitlines():
        direct = bool(AVAILABLE.search(line) and FUTURE_EVENT.search(line))
        since = bool(re.search(r"(?i)\bseit\s+\d{1,2}\.\d{1,2}\.20\d{2}\b", line))
        if not (direct or since):
            continue
        for match in DATE.finditer(line):
            try:
                target = date(int(match[3]), int(match[2]), int(match[1]))
            except ValueError:
                continue
            if target > today:
                issues.append({"line": line.strip()[:300], "date": target.isoformat()})
    return issues


def gate_temporal_claims(answer, today=None):
    issues = future_availability_conflicts(answer, today)
    if not issues:
        return answer
    dates = ", ".join(dict.fromkeys(issue["date"] for issue in issues))
    return (str(answer).rstrip() +
            "\n\n**Zeitprüfung:** Eine Vergangenheitsbehauptung ('seit' oder 'bereits erhältlich') widerspricht "
            f"einem genannten zukünftigen Verkaufsdatum ({dates}). "
            "Bitte Produktstatus separat prüfen.")
