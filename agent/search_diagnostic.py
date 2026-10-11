"""Read-only check of the actual SearXNG JSON search endpoint.

Run: python -m agent.search_diagnostic
Does not start services, write files, or invoke the Google News fallback.
"""
import argparse
import json
import os
from urllib.parse import urlencode, urlsplit

from agent.search_status import request_searxng


def summarize(primary_url, query):
    params = urlencode({"q": query, "format": "json", "language": "de-DE", "safesearch": 0})
    payload, attempts = request_searxng(primary_url, params)
    results = payload.get("results", []) if isinstance(payload, dict) else []
    engines = payload.get("unresponsive_engines", []) if isinstance(payload, dict) else []
    hosts = []
    for result in results[:8]:
        if not isinstance(result, dict):
            continue
        try:
            host = urlsplit(str(result.get("url") or "")).hostname
        except ValueError:
            continue
        if host:
            hosts.append(host)
    return {
        "configured_primary_endpoint": primary_url,
        "provider_attempts": attempts,
        "searxng_results": len(results),
        "result_hosts_sample": hosts,
        "unresponsive_engine_count": len(engines),
        "json_search_usable": bool(results),
        "next_step": (
            "SearXNG returned article search results."
            if results else
            "Check localhost:8081, JSON format support, and SearXNG engine logs."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("SEARXNG_URL",
                        "http://127.0.0.1:8081"))
    parser.add_argument("--query", default="site:apple.com/newsroom iPhone")
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.endpoint, args.query),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
