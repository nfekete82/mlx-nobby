"""Bounded primary-source planning from real search result URLs only.

Titles are ranking hints, never verification evidence. The normal runtime URL
allowlist, permissions, extraction and semantic verification remain mandatory.
"""
import re
from urllib.parse import urlsplit

OFFICIAL_HOSTS = {
    "apple": ("apple.com",),
    "google": ("google.com", "blog.google"),
    "microsoft": ("microsoft.com",),
    "samsung": ("samsung.com",),
}
_AGGREGATORS = ("news.google.com",)
_GENERIC_BRAND_PATH = re.compile(
    r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:iphone|ipad|mac|watch|airpods|"
    r"shop|store|newsroom|products)/?$", re.I,
)
_DATE_ARTICLE = re.compile(r"/newsroom/20\d\d/\d\d/[^/]+", re.I)
_LOCALE_HOME = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?$", re.I)
_CATALOG_TERMS = re.compile(r"\b(?:modell\w*|model\w*|produkt\w*|product\w*|"
                            r"sortiment|lineup|angebot\w*|iphone\w*|ipad\w*)\b", re.I)
_CATALOG_INTENT = re.compile(r"\b(?:welch\w*|aktuell\w*|currently|list\w*|"
                             r"which|available|erhältlich|bietet|offered)\b", re.I)
_OFFICIAL = re.compile(r"\b(?:offiziell\w*|official\w*|herstellerseite)\b", re.I)
_SUBJECT_TERMS = ("iphone", "ipad", "macbook", "airpods", "galaxy", "surface",
                  "pixel", "watch", "laptop", "tablet", "smartphone")


def official_catalog_goal(goal):
    goal = str(goal or "")
    return bool(_OFFICIAL.search(goal) and _CATALOG_TERMS.search(goal)
                and _CATALOG_INTENT.search(goal))


def _brand_for_goal(goal):
    value = str(goal or "").lower()
    names = [brand for brand in OFFICIAL_HOSTS
             if re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", value)]
    return names[0] if len(names) == 1 else None


def _trusted_primary_host(goal, hostname):
    host = (hostname or "").lower().rstrip(".")
    brand = _brand_for_goal(goal)
    if brand:
        return any(host == domain or host.endswith("." + domain)
                   for domain in OFFICIAL_HOSTS[brand])
    return False


def _general_landing_page(url):
    """Country-specific roots and broad category hubs are not product detail."""
    path = urlsplit(url).path or "/"
    return bool(_LOCALE_HOME.fullmatch(path) or _GENERIC_BRAND_PATH.fullmatch(path))


def _direct_official_score(url):
    """Score URL structure only; it cannot establish sale or availability."""
    path = urlsplit(url).path or "/"
    if _DATE_ARTICLE.search(path):
        return 100
    if re.search(r"/(?:shop|store)/buy[-/]", path, re.I):
        return 90
    if "/newsroom/" in path.lower() and not _GENERIC_BRAND_PATH.fullmatch(path):
        return 75
    if _general_landing_page(url):
        return 1
    return 30


def _topic_score(goal, url, title):
    tokens = [t for t in _SUBJECT_TERMS
              if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", str(goal).lower())]
    if not tokens:
        return 0
    path = urlsplit(url).path.lower()
    return 150 if any(t in path or t in title.lower() for t in tokens) else -150


def choose_official_followup(goal, observations):
    goal = str(goal or "").lower()
    if not _OFFICIAL.search(goal):
        return None
    fetched = {
        str(item.get("query") or "")
        for item in observations if isinstance(item, dict)
        and item.get("action") == "fetch_url"
    }
    known_brand = _brand_for_goal(goal) is not None
    catalog = official_catalog_goal(goal)
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
            evidence = " ".join(str(entry.get(k) or "") for k in
                                ("title", "snippet", "description")).lower()
            if known_brand and not _trusted_primary_host(goal, host):
                continue
            if not known_brand and not any(word in evidence for word in
                                           ("official", "offiziell", "hersteller")):
                continue
            if catalog and _general_landing_page(url):
                continue
            priority = _direct_official_score(url) + _topic_score(goal, url, evidence)
            choices.append((priority, url))
    if choices:
        # Prefer a relevant model page over a press article about another device.
        _, url = max(choices, key=lambda item: item[0])
        return {"action": "fetch_url", "query": url,
                "reason": "Spezifische offizielle Quelle aus Suchergebnis prüfen"}
    return None


def choose_official_catalog_refinement(goal, observations):
    """One topical, scoped follow-up query if search exposed no detail pages.

    Never invent source URLs; the ordinary search and fetch allowlist decide
    which URLs may be used. Avoid repeated searches on poor search providers.
    """
    if not official_catalog_goal(goal):
        return None
    brand = _brand_for_goal(goal)
    if not brand:
        return None
    searches = [item for item in observations
                if isinstance(item, dict) and item.get("status") == "completed"
                and item.get("action") in {"search_web", "web_search"}]
    if len(searches) != 1:
        return None
    payload = searches[0].get("result")
    if not isinstance(payload, dict) or payload.get("provider") != "SearXNG":
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    if choose_official_followup(goal, observations) is not None:
        return None
    terms = [term for term in _SUBJECT_TERMS
             if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", str(goal).lower())]
    topic = " ".join(terms[:2]) if terms else "Produkte"
    domain = OFFICIAL_HOSTS[brand][0]
    return {"action": "search_web",
            "query": f"site:{domain} {brand} {topic} Modelle kaufen offiziell",
            "reason": "Einmalige zielgerichtete Suche nach offiziellen Produkt-Detailseiten"}


def insufficient_catalog_sources(goal, observations):
    """Don't stop on homepage copy when the question requests official lineup."""
    if not official_catalog_goal(goal):
        return False
    loaded = []
    for item in observations:
        if not isinstance(item, dict) or item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if (item.get("status") == "completed" and isinstance(result, dict)
                and result.get("ok") is True):
            loaded.append(result.get("url") or result.get("final_url")
                          or result.get("requested_url") or item.get("query") or "")
    if not loaded:
        return False
    return all(_general_landing_page(str(url)) for url in loaded)
