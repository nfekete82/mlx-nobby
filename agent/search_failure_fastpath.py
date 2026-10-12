"""Conservative stop for repeated empty official web searches.

Only completed, explicitly empty observations qualify. Both the legacy tool
envelope and the actual provider diagnostic schema are recognized. An arbitrary
tool error or unfamiliar response never proves that research is exhausted.
"""
from agent.claim_validation import loaded_articles
from urllib.parse import urlsplit

EMPTY_PROVIDER_STATUSES = frozenset({
    "empty", "degraded", "unavailable", "disabled", "rate_limited", "captcha",
    "access_denied", "timeout", "invalid_response",
})
SEARCH_PROVIDERS = frozenset({"SearXNG", "Google News RSS (fallback)", "fallback-unavailable"})


def _known_empty_search(payload):
    if not isinstance(payload, dict) or payload.get("error") not in (None, ""):
        return False
    # Explicit tool failure wins over provider diagnostics.
    if "ok" in payload and payload["ok"] is not True:
        return False
    hits = payload.get("results")
    if not isinstance(hits, list) or hits:
        return False
    if "count" in payload and (type(payload["count"]) is not int or payload["count"] != 0):
        return False
    if payload.get("ok") is True:
        return True
    status, provider = payload.get("provider_status"), payload.get("provider")
    return (isinstance(status, str) and status in EMPTY_PROVIDER_STATUSES
            and isinstance(provider, str) and provider in SEARCH_PROVIDERS)


def _rss_wrapper_only_search(payload):
    """Only an explicitly identified degraded Google News fallback qualifies.

    Nonempty RSS entry lists are not evidence of readable articles.
    Reject mixed/direct source results and all unfamiliar provider shapes.
    """
    if not isinstance(payload, dict) or payload.get("error") not in (None, ""):
        return False
    if payload.get("provider") != "Google News RSS (fallback)":
        return False
    if payload.get("search_degraded") is not True:
        return False
    if payload.get("provider_status") != "available":
        return False
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return False
    if "count" in payload and (type(payload["count"]) is not int or payload["count"] != len(results)):
        return False
    for entry in results:
        if not isinstance(entry, dict) or entry.get("source_type") != "rss_search_entry":
            return False
        try:
            parts = urlsplit(str(entry.get("url") or ""))
        except ValueError:
            return False
        if (parts.scheme != "https" or parts.hostname != "news.google.com"
                or not parts.path.startswith("/rss/articles/")):
            return False
    return True


def exhausted_official_search(goal, observations):
    if not any(word in str(goal or "").casefold()
               for word in ("offiziell", "official", "herstellerseite")):
        return False
    if loaded_articles(observations):
        return False
    searches = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        if item.get("action") not in {"search_web", "web_search"}:
            continue
        if item.get("status") != "completed":
            return False
        payload = item.get("result")
        if not (_known_empty_search(payload) or _rss_wrapper_only_search(payload)):
            return False
        searches.append(payload)
    return len(searches) >= 2


def exhausted_unmatched_item_search(goal, observations):
    """Abstain early for a precise model code with no remotely matching hits.

    Two genuinely distinct completed search queries must both have results,
    but none may mention the exact model code. No fetched document can exist.
    This does NOT prove the item does not exist; it just stops futile searches.
    """
    import re

    request = str(goal or "")
    if not re.search(r"(?i)\b(?:offiziell|official|erhältlich|available)\b", request):
        return False
    identifiers = set(re.findall(r"(?i)\b[A-Z]{1,5}-\d{4,}\b", request))
    if len(identifiers) != 1:
        return False
    if loaded_articles(observations):
        return False
    code = next(iter(identifiers)).casefold()
    searches = []
    for item in observations or []:
        if not isinstance(item, dict) or item.get("action") not in {"search_web", "web_search"}:
            continue
        if item.get("status") != "completed":
            return False
        result = item.get("result")
        if not isinstance(result, dict):
            return False
        hits = result.get("results")
        if not isinstance(hits, list) or not hits:
            return False
        for hit in hits:
            if not isinstance(hit, dict):
                return False
            summary = " ".join(str(hit.get(k) or "") for k in ("title", "url", "snippet"))
            if code in summary.casefold():
                return False
        query = item.get("query")
        if isinstance(query, str) and query.strip():
            searches.append(" ".join(query.casefold().split()))
    return len(set(searches)) >= 2


def exhausted_unreadable_catalog(goal, observations):
    """Fail closed after two distinct official catalog fetches prove unreadable.

    This does not conclude that products are unavailable; it says the
    static HTTP fetcher cannot verify the current retailer listing. Ordinary
    news articles and unrelated companies do not trigger the guard.
    """
    from agent.plan_fastpath import official_catalog_goal, _trusted_primary_host
    if not official_catalog_goal(goal) or loaded_articles(observations):
        return False
    unreadable = set()
    for step in observations or []:
        if not isinstance(step, dict) or step.get("action") != "fetch_url":
            continue
        result = step.get("result")
        if step.get("status") != "completed" or not isinstance(result, dict):
            continue
        if result.get("ok") is True:
            return False
        if "zu wenig verwertbarer seiteninhalt" not in str(
                result.get("error") or "").casefold():
            continue
        url = result.get("url") or step.get("query")
        try:
            parsed = urlsplit(url)
        except (ValueError, TypeError):
            continue
        if parsed.scheme == "https" and _trusted_primary_host(
                goal, parsed.hostname):
            unreadable.add((parsed.hostname.lower(), parsed.path.rstrip("/")))
    return len(unreadable) >= 2


UNAVAILABLE_ANSWER = (
    "Die offizielle Recherche konnte derzeit keine verwertbaren "
    "Suchtreffer oder geladenen Artikel liefern. Deshalb bestätige ich "
    "keine Produkt-, Preis- oder Verfügbarkeitsangaben ohne Belege. "
    "Bitte die Recherche später erneut versuchen oder eine konkrete "
    "offizielle Artikel-URL bereitstellen."
)
