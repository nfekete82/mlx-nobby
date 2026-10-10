"""Optional deterministic next fetch from a completed search result.

Only acts on an explicit official-source request, on safe HTTPS article paths,
with an URL returned by a completed search. Does not execute a tool directly:
normal runtime permission and URL checks still apply.
"""
from urllib.parse import urlsplit


def choose_official_followup(goal, observations):
    goal = str(goal or "").lower()
    if not any(word in goal for word in ("offiziell", "official", "herstellerseite")):
        return None
    fetched = {
        str(item.get("query") or "")
        for item in observations if isinstance(item, dict)
        and item.get("action") == "fetch_url"
    }
    for item in reversed(observations):
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        if item.get("action") not in ("search_web", "web_search"):
            continue
        results = item.get("result")
        entries = results.get("results") if isinstance(results, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries[:6]:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or url in fetched:
                continue
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                continue
            if not parts.path or parts.path == "/":
                continue
            # The result needs an explicit official/primary signal; a high rank
            # alone is insufficient to classify it as official.
            evidence = " ".join(str(entry.get(k) or "") for k in
                                ("title", "snippet", "description")).lower()
            if not any(word in evidence for word in ("official", "offiziell", "hersteller")):
                continue
            return {"action": "fetch_url", "query": url,
                    "reason": "Offizielle Quelle aus Suchergebnis direkt prüfen"}
    return None
