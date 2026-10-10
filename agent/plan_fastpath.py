"""Optional deterministic next fetch from a completed search result.

Only acts on an explicit official-source request, on safe HTTPS article paths,
with an URL returned by a completed search. Does not execute a tool directly:
normal runtime permission and URL checks still apply.
"""
from urllib.parse import urlsplit

OFFICIAL_HOSTS = {"apple": ("apple.com",), "google": ("google.com", "blog.google"), "microsoft": ("microsoft.com",), "samsung": ("samsung.com",)}


def _trusted_primary_host(goal, hostname):
    host = (hostname or "").lower().rstrip(".")
    for brand, hosts in OFFICIAL_HOSTS.items():
        if brand in goal:
            return any(host == domain or host.endswith("." + domain) for domain in hosts)
    return False


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
            try:
                parts = urlsplit(url)
            except ValueError:
                continue
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                continue
            if not parts.path or parts.path == "/":
                continue
            # For a known manufacturer, an untrusted result title cannot
            # establish primary-source ownership (including RSS aggregators).
            evidence = " ".join(str(entry.get(k) or "") for k in
                                ("title", "snippet", "description")).lower()
            known_brand = any(brand in goal for brand in OFFICIAL_HOSTS)
            if known_brand and not _trusted_primary_host(goal, parts.hostname):
                continue
            if not known_brand and not any(word in evidence for word in ("official", "offiziell", "hersteller")):
                continue
            return {"action": "fetch_url", "query": url,
                    "reason": "Offizielle Quelle aus Suchergebnis direkt prüfen"}
    return None
