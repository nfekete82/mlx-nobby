"""Bound web evidence for planning while retaining release-date context.

The complete source remains in the original observations for verification.
"""
import re

_EVENT = re.compile(
    r"(?i)\b(?:vorbestell\w*|pre-?order\w*|erhältlich|verfügbar|available|"
    r"verkaufsstart|marktstart|release|launch|angekündigt|vorgestellt|"
    r"lieferbar|shipping|on sale)\b"
)
_DATE = re.compile(
    r"(?i)\b(?:\d{1,2}\.\s*(?:\d{1,2}\.|januar|februar|märz|"
    r"april|mai|juni|juli|august|september|oktober|november|dezember)"
    r"\s*20\d{2}|20\d{2}-\d{2}-\d{2})\b"
)


def _compact_text(raw, limit=1800, extra=2200):
    if len(raw) <= limit:
        return raw
    # Preserve small, explicitly dated release excerpts even when they fall
    # late in long pages. These are hints for planning, not verified facts.
    snippets = []
    for line in raw.splitlines():
        if not (_EVENT.search(line) and _DATE.search(line)):
            continue
        clipped = line.strip()[:420]
        if clipped and clipped not in snippets:
            snippets.append(clipped)
        if len("\n".join(snippets)) >= extra:
            break
    context = "\n".join(snippets)
    return raw[:limit] + ("\n[WEITERE DATIERTE PRODUKT-HINWEISE]\n" + context[:extra]
                          if context else "")


def compact_web_planning(items):
    result = []
    for item in items:
        if not isinstance(item, dict) or item.get("action") not in (
            "fetch_url", "search_web", "web_search"
        ):
            result.append(item)
            continue
        entry = dict(item)
        payload = entry.get("result")
        if isinstance(payload, dict):
            payload = dict(payload)
            if isinstance(payload.get("text"), str):
                payload["text"] = _compact_text(payload["text"])
            hits = payload.get("results")
            if isinstance(hits, list):
                payload["results"] = [
                    {k: v[:300] if isinstance(v, str) and k != "url" else v
                     for k, v in hit.items() if k in ("url", "title", "snippet")}
                    for hit in hits[:8] if isinstance(hit, dict)
                ]
            entry["result"] = payload
        result.append(entry)
    return result
