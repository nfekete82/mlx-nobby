"""Bounded follow-up when a generic downloads page cannot answer support-policy questions.

Derive the hostname only from an already fetched, public HTTPS source and
require a strong lexical match to the requested named project. The follow-up
search creates no URL. Only actually returned safe search links can be fetched
through the normal guarded tools.
"""
import re
from urllib.parse import urlsplit

_SUPPORT = re.compile(r"\b(?:unterstützt\w*|support(?:ed|s|ing)?|"
                      r"end[- ]of[- ]life|lebenszyklus|versionsrichtlinie)\b", re.I)
_VERSION = re.compile(r"\b(?:hauptversion\w*|version\w*|release\w*)\b", re.I)
_RELEVANT_PATH = re.compile(
    r"/(?:support|versioning|versions|lifecycle|end-of-life|eol)(?:/|-|$)", re.I
)
_POLICY_TITLE = re.compile(r"(?:versioning|support(?:ed)? versions|lifecycle|"
                           r"end.of.life|versionsrichtlinie|unterstützte versionen)", re.I)


def support_policy_question(goal):
    value = str(goal or "")
    return bool(_SUPPORT.search(value) and _VERSION.search(value))


def _matching_source_domain(goal, observations):
    text = str(goal or "").lower()
    for item in reversed(observations):
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        if item.get("action") != "fetch_url":
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        url = result.get("final_url") or result.get("url")
        if not isinstance(url, str):
            continue
        try:
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                continue
            host = parts.hostname.lower().rstrip(".")
            if host.startswith("www."):
                host = host[4:]
            stem = host.split(".")[0]
            if (len(stem) < 4 or not re.search(r"(?<!\w)" + re.escape(stem) + r"(?!\w)", text)):
                continue
            return host
        except ValueError:
            continue
    return None


def need_support_policy_source(goal, observations):
    if not support_policy_question(goal):
        return False
    host = _matching_source_domain(goal, observations)
    if not host:
        return False
    fetched = [
        (item.get("result") or {}).get("final_url") or
        (item.get("result") or {}).get("url") or ""
        for item in observations
        if isinstance(item, dict) and item.get("action") == "fetch_url"
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and item["result"].get("ok") is True
    ]
    return bool(fetched) and not any(
        _RELEVANT_PATH.search(urlsplit(url).path) for url in fetched
        if isinstance(url, str)
    )


def choose_support_policy_followup(goal, observations):
    if not need_support_policy_source(goal, observations):
        return None
    host = _matching_source_domain(goal, observations)
    searches = [item for item in observations
                if isinstance(item, dict) and item.get("status") == "completed"
                and item.get("action") in {"search_web", "web_search"}]
    fetched = {str(item.get("query") or "")
               for item in observations if isinstance(item, dict)
               and item.get("action") == "fetch_url"}
    ranked = []
    for search in searches:
        result = search.get("result")
        entries = result.get("results") if isinstance(result, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                continue
            url = entry["url"]
            if url in fetched:
                continue
            try:
                parts = urlsplit(url)
                domain = (parts.hostname or "").lower().rstrip(".")
                if (parts.scheme != "https" or parts.username or parts.password
                        or not (domain == host or domain.endswith("." + host))):
                    continue
            except ValueError:
                continue
            score = 10 * bool(_RELEVANT_PATH.search(parts.path))
            score += 5 * bool(_POLICY_TITLE.search(str(entry.get("title") or "")))
            if score >= 10:
                ranked.append((score, url))
    if ranked:
        return {"action": "fetch_url", "query": max(ranked, key=lambda x: x[0])[1],
                "reason": "Offizielle Versionsrichtlinie statt generischer Downloadseite lesen"}
    if len(searches) != 1:
        return None
    return {"action": "search_web",
            "query": f"site:{host} supported major versions versioning policy lifecycle",
            "reason": "Einmalige präzise Suche nach offizieller Support-/Versionsrichtlinie"}


# Anchoring a publisher's genuine support matrix requires the table header and
# its nearby rows to remain together. These windows are byte-for-byte substrings
# of the fetched page, not generated or inferred version claims.
_SUPPORT_MATRIX_HEADING = re.compile(
    r"(?im)^[^\n]{0,180}\bversions?\b[^\n]{0,130}"
    r"\b(?:supported|support\s+status|unterstützt|active)\b[^\n]{0,200}$"
)


def support_policy_windows(goal, text, *, max_windows=2):
    """Return bounded, full-line source spans for supported-version tables."""
    if not support_policy_question(goal) or not isinstance(text, str):
        return []
    windows = []
    for match in _SUPPORT_MATRIX_HEADING.finditer(text):
        start = match.start()
        end = min(len(text), start + 1550)
        if end < len(text):
            newline = text.rfind("\n", start + 80, end)
            if newline < 0:
                continue
            end = newline
        block = text[start:end]
        if len(block) < 80 or any(abs(start - prev[0]) < 1000 for prev in windows):
            continue
        windows.append((start, end, block))
        if len(windows) >= max_windows:
            break
    return windows
