"""Direct, bounded, source-grounded weather forecasts for explicit cities.

No chat history, files, location inference, or local network access.
Read-only HTTPS requests to the fixed Open-Meteo geocoding/forecast APIs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from backend.weather_search import is_weather_query

_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_SIMPLE_WEATHER = re.compile(
    r"(?i)^\\s*(?:wetter(?:vorhersage|prognose|bericht)?|"
    r"das\\s+wetter|aktuelles\\s+wetter|weather|"
    r"wie\\s+(?:wird|ist|sieht|schaut)|"
    r"was\\s+(?:ist|wird)|wird\\s+es)\\b"
)
_PLACE = re.compile(r"(?i)\b(?:in|f[uü]r|bei)\s+([^?!.;,]{2,65})")
_BARE = re.compile(
    r"(?i)^\s*(?:das\s+)?wetter(?:vorhersage|prognose|bericht)?"
    r"\s+(?:(?:heute|morgen)\s+)?([^?!.;,]{2,65})"
)
_DAY_WORDS = re.compile(
    r"(?i)\b(?:heute|morgen|übermorgen|aktuell|jetzt|am\s+wochenende|"
    r"diese\s+woche|in\s+deutschland|bitte|denn)\b"
)
_WMO = {
    0: "klar", 1: "überwiegend klar", 2: "teilweise bewölkt",
    3: "bewölkt", 45: "neblig", 48: "neblig",
    51: "leichter Nieselregen", 53: "Nieselregen",
    55: "starker Nieselregen", 56: "gefrierender Nieselregen",
    57: "gefrierender Nieselregen", 61: "leichter Regen",
    63: "Regen", 65: "starker Regen", 66: "gefrierender Regen",
    67: "gefrierender Regen", 71: "leichter Schneefall",
    73: "Schneefall", 75: "starker Schneefall",
    77: "Schneegriesel", 80: "leichte Regenschauer",
    81: "Regenschauer", 82: "starke Regenschauer",
    85: "Schneeschauer", 86: "starke Schneeschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel",
    99: "Gewitter mit Hagel",
}


def _fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(ch)
    )


def weather_request(prompt: str):
    """Return (city, day-offset) for simple current/tomorrow weather questions."""
    text = str(prompt or "").strip()
    if len(text) > 180 or not is_weather_query(text) or not _SIMPLE_WEATHER.search(text):
        return None
    if re.search(r"(?i)\b(?:übermorgen|nächste\s+woche|gestern)\b", text):
        return None
    tomorrow = bool(re.search(r"(?i)\bmorgen\b", text))
    match = _PLACE.search(text) or _BARE.search(text)
    if not match:
        return {"status": "location_required"}
    city = _DAY_WORDS.sub("", match.group(1))
    city = re.sub(r"\s+", " ", city).strip(" .,!?-")
    if not re.fullmatch(r"[\wÄÖÜäöüß][\wÄÖÜäöüß .'-]{1,59}", city, re.UNICODE):
        return {"status": "location_required"}
    return {"status": "ready", "city": city, "offset": 1 if tomorrow else 0}


def _json_get(url: str, opener):
    req = Request(
        url, headers={
            "User-Agent": "MLX-Nobby-Weather/1.0",
            "Accept": "application/json",
        },
    )
    with opener(req, timeout=6) as response:
        data = response.read(64_000)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict) or value.get("error"):
        raise ValueError("Invalid provider response")
    return value


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def forecast_for_question(prompt: str, *, opener=None, now=None):
    """Return data with status; None means this is not a supported weather question.

    The generated answer is fully deterministic and only contains returned API
    values. No hallucinated conditions, no scraped weather pages.
    """
    request = weather_request(prompt)
    if request is None:
        return None
    if request["status"] != "ready":
        return {
            "status": "location_required",
            "answer": "Für welchen Ort möchtest du das Wetter wissen? "
                      "Nenne mir bitte eine Stadt oder Postleitzahl.",
        }
    opener = opener or urlopen
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    city = request["city"]
    try:
        geo_url = _GEO + "?" + urlencode({
            "name": city, "count": 8, "language": "de",
        })
        geo = _json_get(geo_url, opener)
        options = geo.get("results") or []
        matches = [
            entry for entry in options
            if isinstance(entry, dict)
            and (
                _fold(str(entry.get("name") or "")) == _fold(city)
                or (city.isdigit() and city in [
                    str(code) for code in (entry.get("postcodes") or [])
                ])
            )
            and _number(entry.get("latitude")) is not None
            and _number(entry.get("longitude")) is not None
        ]
        if not matches:
            return {"status": "location_unknown", "answer":
                    f"Ich konnte den Ort \"{city}\" nicht eindeutig finden. "
                    "Bitte nenne die Stadt mit Bundesland oder Land."}
        # Prefer a German exact city match for an unqualified German query,
        # otherwise the most populous exact match, and always show the resolved place.
        options = sorted(matches, key=lambda x: (
            x.get("country_code") == "DE",
            _number(x.get("population")) or 0,
        ), reverse=True)
        place = options[0]
        zone = ZoneInfo(str(place.get("timezone") or "Europe/Berlin"))
        target_date = (now.astimezone(zone).date()
                       + timedelta(days=request["offset"]))
        url = _FORECAST + "?" + urlencode({
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": str(zone),
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "forecast_days": 3,
        })
        data = _json_get(url, opener)
        daily = data.get("daily")
        if not isinstance(daily, dict):
            raise ValueError("Missing forecast")
        dates = daily.get("time")
        if not isinstance(dates, list) or target_date.isoformat() not in dates:
            raise ValueError("Forecast date missing")
        i = dates.index(target_date.isoformat())
        def pick(key):
            values = daily.get(key)
            return values[i] if isinstance(values, list) and i < len(values) else None

        name = str(place["name"])[:60]
        region = str(place.get("admin1") or "")[:60]
        country = str(place.get("country") or "")[:60]
        place_label = ", ".join(item for item in (name, region, country) if item)
        label = "morgen" if request["offset"] else "heute"
        details = []
        code = pick("weather_code")
        if code in _WMO:
            details.append(_WMO[code])
        lo = _number(pick("temperature_2m_min"))
        hi = _number(pick("temperature_2m_max"))
        if lo is not None and hi is not None:
            details.append(f"{lo:g}–{hi:g} °C")
        prob = _number(pick("precipitation_probability_max"))
        if prob is not None and 0 <= prob <= 100:
            details.append(f"max. {prob:g} % Regenwahrscheinlichkeit")
        if not details:
            raise ValueError("Missing forecast values")
        current = data.get("current") or {}
        if request["offset"] == 0 and isinstance(current, dict):
            if str(current.get("time") or "")[:10] == target_date.isoformat():
                temp = _number(current.get("temperature_2m"))
                if temp is not None:
                    details.insert(0, f"aktuell {temp:g} °C")
        summary = (f"Wetter für {place_label} {label} "
                   f"({target_date.strftime('%d.%m.%Y')}): "
                   + "; ".join(details) + ".")
        return {
            "status": "available", "answer": summary + (
                "\nQuelle: Open-Meteo (modellbasierte Wettervorhersage): " + url
            ),
            "source_url": url, "location": name,
            "target_date": target_date.isoformat(),
        }
    except (OSError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
        return {"status": "unavailable", "answer":
                "Die aktuellen Wetterdaten sind momentan nicht erreichbar. "
                "Ich möchte keine Vorhersage erfinden. Bitte erneut versuchen."}
