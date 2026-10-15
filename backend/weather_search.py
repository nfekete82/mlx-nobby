"""Conservative web-weather search quality safeguards.

Do not substitute generic web/news snippets for meteorological forecasts.
The service cannot infer a physical location from "weather today" alone.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


WEATHER_QUERY = re.compile(
    r"(?i)\b(?:wetter(?:vorhersage|bericht|prognose)?|"
    r"weather|regnet|regenwahrscheinlichkeit)\b"
)
# Narrowly scoped common standalone requests that do not mention a place.
NO_LOCATION_WEATHER = re.compile(
    r"(?ix)^\s*(?:"
    r"wie\s+(?:wird|ist)\s+(?:denn\s+)?(?:das\s+)?wetter"
    r"|wie\s+(?:sieht|schaut)\s+(?:das\s+)?wetter\s+aus"
    r"|(?:das\s+)?wetter(?:vorhersage|prognose|bericht)?"
    r"|wird\s+es\s+(?:(?:heute|morgen|übermorgen)\s+)?regnen"
    r")\s*(?:(?:heute|morgen|übermorgen|am\s+wochenende|diese\s+woche)"
    r"(?:\s+(?:wohl|noch))?)?\s*[?!. ]*$"
)
# Official and established meteorological sources, not topical hit count.
WEATHER_HOSTS = (
    "dwd.de", "wetter.de", "wetter.com", "wetteronline.de",
    "meteoblue.com", "open-meteo.com", "weather.com",
    "kachelmannwetter.com", "meteoswiss.admin.ch",
    "zamg.ac.at", "geosphere.at",
)
FORECAST_TITLE = re.compile(
    r"(?i)\b(?:wetter(?:vorhersage|prognose|bericht)?|"
    r"weather|temperatur(?:en)?|niederschlag|"
    r"vorhersage|prognose|regenradar)\b"
)


def is_weather_query(prompt: str) -> bool:
    return bool(WEATHER_QUERY.search(str(prompt or "")))


def is_locationless_weather_question(prompt: str) -> bool:
    return bool(NO_LOCATION_WEATHER.fullmatch(str(prompt or "")))


def relevant_forecast_result(title: str, url: str) -> bool:
    """Reject unrelated search hits, even if ranked first."""
    if not FORECAST_TITLE.search(str(title or "")):
        return False
    try:
        parsed = urlparse(str(url))
    except (ValueError, TypeError):
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and any(
        host == domain or host.endswith("." + domain)
        for domain in WEATHER_HOSTS
    )
