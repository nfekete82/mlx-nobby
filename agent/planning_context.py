"""Bound web tool text for agent planning only, retaining raw evidence elsewhere."""

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
                payload["text"] = payload["text"][:1800]
            hits = payload.get("results")
            if isinstance(hits, list):
                payload["results"] = [
                    {k: v[:300] if isinstance(v, str) else v
                     for k, v in hit.items() if k in ("url", "title", "snippet")}
                    for hit in hits[:8] if isinstance(hit, dict)
                ]
            entry["result"] = payload
        result.append(entry)
    return result
