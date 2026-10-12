"""Diagnose should distinguish irrelevant results from usable primary hits."""
from urllib.parse import parse_qs
from unittest.mock import patch

from agent.search_diagnostic import summarize


def test_diagnostic_uses_nasa_locale_and_flags_publisher_mismatch():
    payload = {"results": [
        {"url": "https://www.apollo.de/", "title": "Optiker"},
        {"url": "https://de.wikipedia.org/wiki/NASA", "title": "NASA"},
    ], "unresponsive_engines": [
        ["qwant", "CAPTCHA"], ["yahoo", "HTTP protocol error"],
    ]}
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(payload, [{"provider": "SearXNG", "status": "available"}])) as request:
        report = summarize("http://127.0.0.1:8081", "site:nasa.gov Apollo 11 moon landing")
    query = parse_qs(request.call_args.args[1])
    assert query["language"] == ["en-US"]
    assert report["search_language"] == "en-US"
    assert report["primary_host_hit_count"] == 0
    assert report["json_search_usable"] is False
    assert "none from" in report["next_step"]
    assert [e["status"] for e in report["unresponsive_engines"]] == [
        "captcha", "unavailable",
    ]


def test_diagnostic_recognizes_official_bpb_result():
    payload = {"results": [
        {"url": "https://www.bpb.de/themen/deutschlandarchiv/mauerfall/",
         "title": "Mauerfall"},
    ], "unresponsive_engines": []}
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(payload, [])) as request:
        report = summarize("http://127.0.0.1:8081", "Berliner Mauer Mauerfall bpb.de")
    assert parse_qs(request.call_args.args[1])["language"] == ["de-DE"]
    assert report["primary_host_hit_count"] == 1
    assert report["json_search_usable"] is True
