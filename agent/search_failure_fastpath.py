"""Conservative stop for repeated empty official web searches.

Only completed, explicitly empty observations qualify. Both the legacy tool
envelope and the actual provider diagnostic schema are recognized. An arbitrary
tool error or unfamiliar response never proves that research is exhausted.
"""
from agent.claim_validation import loaded_articles

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
        if not _known_empty_search(payload):
            return False
        searches.append(payload)
    return len(searches) >= 2


UNAVAILABLE_ANSWER = (
    "Die offizielle Recherche konnte derzeit keine verwertbaren "
    "Suchtreffer oder geladenen Artikel liefern. Deshalb bestätige ich "
    "keine Produkt-, Preis- oder Verfügbarkeitsangaben ohne Belege. "
    "Bitte die Recherche später erneut versuchen oder eine konkrete "
    "offizielle Artikel-URL bereitstellen."
)
