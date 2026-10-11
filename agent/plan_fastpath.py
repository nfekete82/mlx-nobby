"""Optional deterministic next fetch from completed web search results.

Use only HTTPS URLs actually returned by a completed search. Prioritize
specific manufacturer announcements/official store product pages over general
category landing pages. Search snippets and titles never create source trust.
The normal runtime allowlist and permissions still apply.
"""
import re
from urllib.parse import urlsplit

OFFICIAL_HOSTS = {"apple": ("apple.com",), "google": ("google.com", "blog.google"),
                  "microsoft": ("microsoft.com",), "samsung": ("samsung.com",)}
_AGGREGATORS = ("news.google.com",)
_GENERIC_BRAND_PATH = re.compile(
    r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:iphone|ipad|mac|watch|airpods|"
    r"shop|store|newsroom|products)/?$", re.I,
)
_DATE_ARTICLE = re.compile(r"/newsroom/20\d\d/\d\d/[^/]+", re.I)


def _trusted_primary_host(goal, hostname):
    host = (hostname or "").lower().rstrip(".")
    for brand, hosts in OFFICIAL_HOSTS.items():
        if brand in goal:
            return any(host == domain or host.endswith("." + domain) for domain in hosts)
    return False


def _direct_official_score(url):
    """Score structure only; it cannot establish sale or availability."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if _DATE_ARTICLE.search(path):
        return 100
    if re.search(r"/(?:shop|store)/buy[-/]", path, re.I):
        return 90
    if "/newsroom/" in path.lower() and not _GENERIC_BRAND_PATH.fullmatch(path):
        return 75
    if _GENERIC_BRAND_PATH.fullmatch(path):
        return 1
    return 30


def choose_official_followup(goal, observations):
    goal = str(goal or "").lower()
    if not any(word in goal for word in ("offiziell", "official", "herstellerseite")):
        return None
    fetched = {
        str(item.get("query") or "")
        for item in observations if isinstance(item, dict)
        and item.get("action") == "fetch_url"
    }
    known_brand = any(brand in goal for brand in OFFICIAL_HOSTS)
    choices = []
    for observation in reversed(observations):
        if not isinstance(observation, dict) or observation.get("status") != "completed":
            continue
        if observation.get("action") not in ("search_web", "web_search"):
            continue
        result = observation.get("result")
        entries = result.get("results") if isinstance(result, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries[:8]:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or url in fetched:
                continue
            try:
                parts = urlsplit(url)
            except ValueError:
                continue
            if (parts.scheme != "https" or not parts.hostname or parts.username
                    or parts.password or not parts.path or parts.path == "/"):
                continue
            host = parts.hostname.lower().rstrip(".")
            if host in _AGGREGATORS or entry.get("source_type") == "rss_search_entry":
                continue
            # A result title that says "official" cannot promote an RSS
            # aggregator or another third-party host to an Apple source.
            evidence = " ".join(str(entry.get(k) or "") for k in
                                ("title", "snippet", "description")).lower()
            if known_brand and not _trusted_primary_host(goal, host):
                continue
            if not known_brand and not any(word in evidence for word in
                                           ("official", "offiziell", "hersteller")):
                continue
            priority = _direct_official_score(url)
            choices.append((priority, url))
    if choices:
        # Within an equal tier preserve the search-provider's original order.
        _, url = max(choices, key=lambda item: item[0])
        return {"action": "fetch_url", "query": url,
                "reason": "Gezielte offizielle Quelle aus Suchergebnis direkt prüfen"}
    return None
