"""Diagnostic reports backend health without invoking news search fallbacks."""
from unittest.mock import patch

from agent.search_diagnostic import summarize


def test_reports_available_real_search_links():
    payload = {"results": [
        {"url": "https://www.apple.com/newsroom/2026/09/example"},
        {"url": "https://www.example.com/article"},
    ], "unresponsive_engines": []}
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(payload, [{"provider": "SearXNG", "status": "available"}])) as mock:
        report = summarize("http://127.0.0.1:8081", "site:apple.com/newsroom iPhone")
    assert report["json_search_usable"] is True
    assert report["searxng_results"] == 2
    assert report["result_hosts_sample"] == ["www.apple.com", "www.example.com"]
    assert report["unresponsive_engine_count"] == 0
    args = mock.call_args.args
    assert "format=json" in args[1]


def test_reports_unavailable_provider_without_fake_success():
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(None, [{"provider": "SearXNG", "status": "unavailable"}])):
        report = summarize("http://127.0.0.1:8081", "iPhone")
    assert report["json_search_usable"] is False
    assert report["searxng_results"] == 0
    assert report["provider_attempts"][0]["status"] == "unavailable"


def test_degraded_empty_response_is_not_reported_healthy():
    payload = {"results": [], "unresponsive_engines": [{"engine": "google"}]}
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(payload, [{"provider": "SearXNG", "status": "degraded"}])):
        report = summarize("http://127.0.0.1:8081", "iPhone")
    assert report["unresponsive_engine_count"] == 1
    assert report["json_search_usable"] is False


def test_sample_does_not_expose_url_tokens_or_page_text():
    payload = {"results": [{"url": "https://example.org/article?token=private-secret",
                            "title": "Secret page"}]}
    with patch("agent.search_diagnostic.request_searxng",
               return_value=(payload, [{"provider": "SearXNG", "status": "available"}])):
        report = summarize("http://127.0.0.1:8081", "iPhone")
    assert "private-secret" not in str(report)
    assert "Secret page" not in str(report)
