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


def choose_support_policy_research_step(goal, observations):
    """Avoid LLM planning for a *narrow* named official support-policy lookup.

    An initial search string is never evidence. Every fetched URL must come
    verbatim from an actual search result or a loaded page's same-site links.
    Keep the ordinary planner for unknown publishers and failed discovery.
    """
    if not support_policy_question(goal) or re.search(
        r"(?i)\b(?:vergleich\w*|compare|compared|versus)\b", str(goal)
    ):
        return None
    # Import lazily to reuse the exact hostname whitelist used by the
    # source-exact support matrix, avoiding a second divergent trust list.
    from agent.support_table_evidence import _OFFICIAL_POLICY_HOSTS
    value = str(goal or "")
    matches = [
        (stem, host)
        for stem, host in _OFFICIAL_POLICY_HOSTS.items()
        if re.search(r"(?<!\w)" + re.escape(stem) + r"(?!\w)", value, re.I)
    ]
    if len(matches) != 1:
        return None
    stem, host = matches[0]
    if not observations:
        # Query terms are only discovery hints; search/fetch permissions and
        # semantic source verification remain entirely unchanged.
        return {
            "action": "search_web",
            "query": f"{stem} versioning policy supported major versions official",
            "reason": "Offizielle Versionsrichtlinie gezielt suchen",
        }

    attempted = {
        str(item.get("query") or "")
        for item in observations
        if isinstance(item, dict) and item.get("action") == "fetch_url"
    }
    # Reuse actual public URLs only. Never synthesize /support/versioning/.
    candidates = []
    for item in observations:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        links = ()
        if item.get("action") in {"search_web", "web_search"}:
            links = result.get("results")
        elif item.get("action") == "fetch_url" and result.get("ok") is True:
            origin = result.get("final_url") or result.get("url")
            try:
                parsed_origin = urlsplit(origin)
                if (parsed_origin.scheme != "https"
                        or parsed_origin.hostname not in {host, "www." + host}
                        or parsed_origin.username or parsed_origin.password
                        or parsed_origin.port not in {None, 443}):
                    continue
            except (ValueError, TypeError):
                continue
            links = result.get("page_links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            url = link.get("url")
            if not isinstance(url, str) or url in attempted or len(url) > 1200:
                continue
            try:
                parts = urlsplit(url)
                if (parts.scheme != "https"
                        or parts.hostname not in {host, "www." + host}
                        or parts.username or parts.password
                        or parts.port not in {None, 443}
                        or not _RELEVANT_PATH.search(parts.path)):
                    continue
            except ValueError:
                continue
            # Prioritize an exact policy page over a generic support index.
            title = str(link.get("title") or "")
            score = 20 * bool(re.search(r"/versioning(?:/|$)", parts.path, re.I))
            score += 10 * bool(_POLICY_TITLE.search(title))
            score += 5 * bool(re.search(r"/(?:versions|lifecycle)(?:/|$)", parts.path, re.I))
            # /support/ alone is a generic index, not a version matrix.
            # Do not treat it as sufficient evidence for this question.
            if score <= 0:
                continue
            candidates.append((score, url))
    if not candidates:
        # Some search engines omit the support policy page but expose the
        # publisher's general download index. Reading the *returned* index
        # is preferable to spending a model call picking the same URL.
        # Only the first search can take this route, at most once per run.
        searches = [
            item for item in observations
            if isinstance(item, dict)
            and item.get("action") in {"search_web", "web_search"}
            and item.get("status") == "completed"
            and isinstance(item.get("result"), dict)
        ]
        if len(searches) == 1 and not attempted:
            fallback_urls = []
            for link in searches[0]["result"].get("results", []):
                if not isinstance(link, dict) or link.get("source_type") == "rss_search_entry":
                    continue
                url = link.get("url")
                if not isinstance(url, str) or len(url) > 1200:
                    continue
                try:
                    parts = urlsplit(url)
                    if (
                        parts.scheme == "https"
                        and parts.hostname in {host, "www." + host}
                        and parts.username is None
                        and parts.password is None
                        and parts.port in {None, 443}
                        and re.fullmatch(r"/download/?", parts.path, re.I)
                        and not parts.query
                        and not parts.fragment
                    ):
                        fallback_urls.append(url)
                except ValueError:
                    continue
            if fallback_urls:
                return {
                    "action": "fetch_url",
                    "query": fallback_urls[0],
                    "reason": "Gefundene offizielle Downloadübersicht als Einstieg prüfen",
                }
        return None
    _, url = max(candidates, key=lambda item: item[0])
    return {
        "action": "fetch_url",
        "query": url,
        "reason": "Gefundene offizielle Versionsrichtlinie direkt prüfen",
    }


# Anchoring a publisher's genuine support matrix requires the table header and
# its nearby rows to remain together. These windows are byte-for-byte substrings
# of the fetched page, not generated or inferred version claims.
_SUPPORT_MATRIX_HEADING = re.compile(
    # A real extracted HTML table has pipe-separated cells. Requiring the
    # column boundary prevents ordinary prose like "version is supported"
    # from displacing the actual status matrix in the limited evidence budget.
    r"(?im)^[^\n]{0,80}\bversions?\s*\|[^\n]{0,150}"
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
