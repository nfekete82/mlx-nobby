"""Conservative timestamp validation for explicitly same-day public news.

A search engine result is not a verified article. Do not pass dated older
headlines (or undated links) as evidence for a request about *today*.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from zoneinfo import ZoneInfo


_LOCAL_NEWS_TZ = ZoneInfo("Europe/Berlin")
_NEWS_TERMS = re.compile(
    r"\b(?:(?:börsen|aktien|finanz|wirtschafts)[\s-]*(?:news|nachrichten)"
    r"|news|nachrichten|schlagzeilen|meldungen|topnews|headlines)\b",
    re.IGNORECASE,
)
_TODAY_TERMS = re.compile(
    r"\b(?:heute|today|heutig(?:e|en|er|es)?)\b",
    re.IGNORECASE,
)


def requires_today_news(query: str) -> bool:
    """Use strict per-day freshness only when a today-news intent is explicit."""
    value = str(query or "")
    return bool(_NEWS_TERMS.search(value) and _TODAY_TERMS.search(value))


def publication_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        candidate = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            candidate = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if candidate.tzinfo is None:
        # No timezone -> no reliable assignment to a local calendar day.
        return None
    return candidate.astimezone(timezone.utc)


def filter_today_news(results, *, now=None):
    """Drop unsupported or stale results, preserving provider result order."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_day = now.astimezone(_LOCAL_NEWS_TZ).date()
    kept = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        published = publication_time(entry.get("published_date"))
        if published is None or published > now:
            continue
        if published.astimezone(_LOCAL_NEWS_TZ).date() == local_day:
            kept.append(entry)
    return kept
