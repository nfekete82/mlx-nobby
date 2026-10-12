"""Read-only check of the actual SearXNG JSON search endpoint.

Run: python -m agent.search_diagnostic
Does not start services, write files, or invoke the Google News fallback.
"""
import argparse
import json
import os
import re
from urllib.parse import urlencode, urlsplit

from agent.search_status import classify_search_failure, request_searxng


def _engine_failures(unresponsive):
    """Keep only safe engine identifiers and diagnostic classes, not raw error text."""
    issues = []
    for entry in unresponsive[:20] if isinstance(unresponsive, list) else []:
        if isinstance(entry, dict):
            name = entry.get("engine") or entry.get("name")
            reason = entry.get("reason") or entry.get("error")
        elif isinstance(entry, (list, tuple)):
            name = entry[0] if entry else None
            reason = entry[1] if len(entry) > 1 else None
        else:
            name, reason = entry, None
        name = str(name or "").strip()[:70]
        if not re.fullmatch(r"[A-Za-z0-9_ .+-]{1,70}", name):
            name = "unknown_engine"
        issues.append({"engine": name, "status": classify_search_failure(reason)})
    return issues


def summarize(primary_url, query):
    # Run the same locale policy as the live agent. English NASA documents
    # should not be evaluated through an artificially forced German locale.
    from agent.app import web_search_language_for_query
    from agent.search_relevance import required_site
    language = web_search_language_for_query(query)
    params = urlencode({"q": query, "format": "json", "language": language, "safesearch": 0})
    payload, attempts = request_searxng(primary_url, params)
    results = payload.get("results", []) if isinstance(payload, dict) else []
    engines = payload.get("unresponsive_engines", []) if isinstance(payload, dict) else []
    hosts = []
    official_domain = required_site(query)
    if not official_domain:
        match = re.search(r"(?i)(?<![a-z0-9.-])(nasa\.gov|bpb\.de)(?![a-z0-9.-])", query)
        official_domain = match.group(1).casefold() if match else None
    official_matches = 0
    for result in results[:8]:
        if not isinstance(result, dict):
            continue
        try:
            host = urlsplit(str(result.get("url") or "")).hostname
        except ValueError:
            continue
        if host:
            hosts.append(host)
    if official_domain:
        for result in results:
            if not isinstance(result, dict):
                continue
            try:
                host = (urlsplit(str(result.get("url") or "")).hostname or "").lower().rstrip(".")
            except ValueError:
                continue
            if host == official_domain or host.endswith("." + official_domain):
                official_matches += 1
    return {
        "configured_primary_endpoint": primary_url,
        "search_language": language,
        "requested_primary_host": official_domain,
        "primary_host_hit_count": official_matches if official_domain else None,
        "provider_attempts": attempts,
        "searxng_results": len(results),
        "result_hosts_sample": hosts,
        "unresponsive_engine_count": len(engines),
        "unresponsive_engines": _engine_failures(engines),
        "json_search_usable": bool(results) and (not official_domain or official_matches > 0),
        "next_step": (
            "SearXNG returned results, but none from the requested primary publisher."
            if results and official_domain and not official_matches else
            "SearXNG returned search results; verify article relevance separately."
            if results else
            "Inspect unresponsive_engines and SearXNG logs; JSON is responding but returned no results."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("SEARXNG_URL",
                        "http://127.0.0.1:8081"))
    parser.add_argument("--query", default="Apple iPhone")
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.endpoint, args.query),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
