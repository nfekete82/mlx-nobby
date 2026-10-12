"""Fail-closed response for explicitly official web research without article evidence.

A warning appended to fabricated launch or confirmation details is not enough.
Only applies when a web tool was actually attempted and the user explicitly
requested official source verification; ordinary local/coding queries are untouched.
"""
from agent.claim_validation import loaded_articles

_WEB = {"search_web", "web_search", "fetch_url"}


def gate_unverified_official_answer(answer, goal, observations):
    request = str(goal or "").casefold()
    if not any(term in request for term in ("offiziell", "official", "herstellerseite")):
        return answer
    if not any(isinstance(o, dict) and o.get("action") in _WEB for o in observations or []):
        return answer
    if loaded_articles(observations):
        return answer
    return (
        "Ich konnte die gewünschten Angaben nicht anhand tatsächlich geladener "
        "offizieller Artikel verifizieren. Die Websuche oder der Artikelabruf "
        "hat keine ausreichende Evidenz geliefert. Deshalb nenne ich keine "
        "unbestätigten Produkt-, Verkaufsstart- oder Verfügbarkeitsangaben als Fakten. "
        "Bitte die offizielle Herstellerquelle direkt prüfen oder die Recherche "
        "erneut versuchen."
    )
