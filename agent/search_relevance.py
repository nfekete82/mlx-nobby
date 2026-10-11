"""Search-result site: scoping without granting any source authority.

Public SearXNG engines may ignore site: queries and return unrelated hosts.
Reject those hits rather than treating them as relevant research evidence.
This filter is not a fact verifier. The normal public-URL/SSRF guard still applies.
"""
import re
from urllib.parse import urlsplit

_SITE = re.compile(r"(?i)(?<!\S)site:([a-z0-9][a-z0-9.-]*\.[a-z]{2,})(?:/\S*)?")


def required_site(query):
    terms = _SITE.findall(str(query or ""))
    return terms[0].lower().rstrip(".") if len(terms) == 1 else None


def filter_site_results(query, results):
    """Return (filtered results, observed mismatches) for one explicit site:."""
    domain = required_site(query)
    if not domain or not isinstance(results, list):
        return results, 0
    filtered = []
    removed = 0
    for hit in results:
        if not isinstance(hit, dict):
            removed += 1
            continue
        try:
            parts = urlsplit(hit.get("url") or "")
            hostname = (parts.hostname or "").lower().rstrip(".")
            allowed = parts.scheme == "https" and (
                hostname == domain or hostname.endswith("." + domain))
        except (ValueError, TypeError):
            allowed = False
        if allowed:
            filtered.append(hit)
        else:
            removed += 1
    return filtered, removed
