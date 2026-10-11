"""Conservative stop for repeated empty official web searches.

Only a strict sequence of two completed, empty successful searches qualifies.
Never infer failure from an unfamiliar schema or a temporary tool error.
"""
from agent.claim_validation import loaded_articles


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
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return False
        hits = payload.get("results")
        if not isinstance(hits, list):
            return False
        searches.append(hits)
    return len(searches) >= 2 and all(not hits for hits in searches)


UNAVAILABLE_ANSWER = (
    "Die offizielle Recherche konnte derzeit keine verwertbaren "
    "Suchtreffer oder geladenen Artikel liefern. Deshalb bestätige ich "
    "keine Produkt-, Preis- oder Verfügbarkeitsangaben ohne Belege. "
    "Bitte die Recherche später erneut versuchen oder eine konkrete "
    "offizielle Artikel-URL bereitstellen."
)
