"""Follow up a loaded current-release download index with an original text focus.

Focus is not an invented release or a fabricated URL. It requests a source-
exact excerpt from the HTTPS page the agent already fetched and remains
subject to the ordinary per-passage semantic verifier.
"""
import re
from urllib.parse import urlsplit


def python_latest_version_question(goal):
    question = str(goal or "").casefold()
    return bool(
        re.search(r"(?:python\.org|\bpython[-\s]*3\b)", question)
        and re.search(r"\b(?:neueste|aktuell\w*|latest|newest|stabile|stable)\b", question)
        and re.search(r"\b(?:version|release|veröffentlicht|released)\b", question)
    )


def python_release_focus_step(goal, observations):
    """One focus on an already-fetched official index; never guess the URL."""
    if not python_latest_version_question(goal):
        return None

    candidates = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") != "completed" or not isinstance(result, dict)
                or result.get("ok") is not True):
            continue
        url = result.get("final_url") or result.get("url")
        try:
            parsed = urlsplit(url)
        except (ValueError, TypeError):
            continue
        if (parsed.scheme != "https" or
                parsed.hostname not in {"www.python.org", "python.org"} or
                parsed.path.rstrip("/") != "/downloads"):
            continue
        if result.get("focus") is not None:
            return None
        candidates.append(url)

    if not candidates:
        return None
    url = candidates[-1]
    for item in observations or []:
        if (not isinstance(item, dict) or item.get("action") != "fetch_url"
                or str(item.get("query") or "") != url):
            continue
        if "focus=" in str(item.get("instruction") or "").casefold():
            return None
    return {
        "action": "fetch_url",
        "query": url,
        "instruction": "focus=Active Python releases",
        "reason": "Originalen aktuellen Versionsabschnitt der zuvor geladenen offiziellen Downloadseite lesen",
    }


def needs_python_release_focus(goal, observations):
    return python_release_focus_step(goal, observations) is not None
