"""Conservative, explicit weather-slot continuation for the regular chat API.

Only the immediately relevant weather exchange is used. No persisted location,
geolocation, unrelated chat history or global state.
"""
import re
from backend.weather_forecast import weather_request

_LOCATION = re.compile(r"^[\wÄÖÜäöüß][\wÄÖÜäöüß .'-]{1,59}$", re.UNICODE)
_DAY = re.compile(r"(?i)^\s*(?:und\s+)?(?:wie\s+(?:ist|wird)\s+(?:es\s+)?)?(heute|morgen)\s*\??\s*$")


def weather_context_query(prompt, history):
    """Return explicit complete weather question, or None when uncertain."""
    if not isinstance(history, list) or not history or len(history) > 40:
        return None
    text = str(prompt or "").strip()
    recent = [m for m in history[-8:] if isinstance(m, dict)
              and m.get("role") in ("user", "assistant")]
    if not recent or recent[-1].get("role") != "assistant":
        return None
    last_answer = str(recent[-1].get("content") or "")
    if "Für welchen Ort möchtest du das Wetter wissen?" in last_answer:
        if not _LOCATION.fullmatch(text) or text.casefold() in {"ja", "nein", "danke", "morgen", "heute"}:
            return None
        if not any(
            weather_request(str(m.get("content") or "")) is not None
            for m in recent[:-1] if m.get("role") == "user"
        ):
            return None
        return f"Wie wird das Wetter heute in {text}?"
    match = _DAY.fullmatch(text)
    if not match:
        return None
    # The previous answer must be an actual, grounded weather result.
    if not last_answer.startswith("Wetter für "):
        return None
    previous_users = [str(m.get("content") or "") for m in recent[:-1]
                      if m.get("role") == "user"]
    for previous in reversed(previous_users):
        request = weather_request(previous)
        if request and request.get("status") == "ready":
            return f"Wie wird das Wetter {match.group(1).lower()} in {request['city']}?"
    return None
