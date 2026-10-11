"""The official search fastpath only stops proven empty retrieval."""
from agent.search_failure_fastpath import exhausted_official_search
import io
import urllib.error
from unittest.mock import patch

import pytest


def item(hits, *, ok=True, status="completed"):
    return {"action": "search_web", "status": status,
            "result": {"ok": ok, "results": hits}}


def test_two_empty_official_searches_stop():
    assert exhausted_official_search("Apple iPhones offiziell", [item([]), item([])])


def test_one_search_or_nonofficial_request_continues():
    assert not exhausted_official_search("Apple iPhones offiziell", [item([])])
    assert not exhausted_official_search("Apple Handys", [item([]), item([])])


def test_hits_or_errors_do_not_stop():
    goal = "Apple iPhones offiziell"
    assert not exhausted_official_search(goal, [item([]), item([{"url": "https://apple.com"}])])
    assert not exhausted_official_search(goal, [item([]), item([], ok=False)])
    assert not exhausted_official_search(goal, [item([]), item([], status="failed")])


def test_unknown_search_schema_does_not_stop():
    goal = "Apple iPhones offiziell"
    assert not exhausted_official_search(goal, [item([]), {"action": "search_web",
        "status": "completed", "result": {"ok": True}}])


def test_loaded_article_keeps_research_running():
    goal = "Apple iPhones offiziell"
    source = {"action": "fetch_url", "status": "completed",
              "result": {"ok": True, "url": "https://www.apple.com/de/newsroom/item",
                         "text": "Official product announcement. " * 10}}
    assert not exhausted_official_search(goal, [item([]), item([]), source])


def provider_item(payload):
    return {"action": "search_web", "status": "completed", "result": payload}


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("offline"),
    urllib.error.HTTPError("https://news.google.com/rss/search", 429, "too many requests", {}, None),
    urllib.error.HTTPError("https://news.google.com/rss/search", 403, "access denied", {}, None),
    TimeoutError("timed out"),
])
def test_actual_production_provider_failure_payload_can_stop_after_two_searches(failure):
    from agent.app import searxng_search_results
    with patch.dict("os.environ", {"MLX_PUBLIC_SEARCH_FALLBACK": "1"}), \
         patch("agent.app.request_searxng", return_value=(None, [{"provider": "SearXNG", "status": "unavailable"}])), \
         patch("urllib.request.urlopen", side_effect=failure):
        payload = searxng_search_results("Apple iPhones offiziell")
    assert "ok" not in payload
    assert payload["results"] == [] and payload["count"] == 0
    assert exhausted_official_search("Apple iPhones offiziell", [provider_item(payload), provider_item(payload)])


@pytest.mark.parametrize("fallback_disabled", [True, False])
def test_actual_production_empty_or_disabled_fallback_payload_is_recognized(fallback_disabled):
    from agent.app import searxng_search_results
    with patch.dict("os.environ", {"MLX_PUBLIC_SEARCH_FALLBACK": "0" if fallback_disabled else "1"}), \
         patch("agent.app.request_searxng", return_value=({"results": [],
             "unresponsive_engines": [["startpage", "Suspended: CAPTCHA"]]}, [])), \
         patch("urllib.request.urlopen", return_value=io.BytesIO(b"<rss><channel/></rss>")):
        payload = searxng_search_results("Apple iPhones offiziell")
    assert payload["provider_status"] == ("disabled" if fallback_disabled else "empty")
    assert payload["primary_provider_status"] == "degraded"
    assert exhausted_official_search("Apple iPhones offiziell", [provider_item(payload), provider_item(payload)])


@pytest.mark.parametrize("patch_payload", [
    {"ok": False}, {"ok": None}, {"count": 1}, {"count": "0"}, {"count": False},
    {"provider_status": "available"}, {"provider_status": "unknown"},
    {"provider_status": []}, {"provider": "unknown-service"},
    {"error": "tool execution failed"}, {"results": None},
    {"results": [{"url": "https://example.org/article"}]},
])
def test_provider_errors_unknown_schema_or_nonempty_results_do_not_stop(patch_payload):
    payload = {"provider": "Google News RSS (fallback)", "provider_status": "empty",
               "count": 0, "results": []} | patch_payload
    assert not exhausted_official_search("Apple iPhones offiziell", [item([]), provider_item(payload)])


def test_provider_schema_allows_omitted_count_but_requires_known_provider():
    payload = {"provider": "Google News RSS (fallback)", "provider_status": "empty", "results": []}
    assert exhausted_official_search("Apple iPhones offiziell", [provider_item(payload), provider_item(payload)])
    assert not exhausted_official_search("Apple iPhones offiziell", [provider_item(payload),
        provider_item({"provider_status": "empty", "results": []})])


def rss_only_results():
    return {"provider": "Google News RSS (fallback)",
            "provider_status": "available", "search_degraded": True,
            "count": 1,
            "results": [{"url": "https://news.google.com/rss/articles/abc?oc=5",
                         "source_type": "rss_search_entry",
                         "title": "Apple iPhone new device"}]}


def test_two_rss_only_searches_do_not_pretend_to_be_retrieved_articles():
    from agent.search_failure_fastpath import _rss_wrapper_only_search
    payload = rss_only_results()
    assert _rss_wrapper_only_search(payload)
    assert exhausted_official_search("Welche iPhones verkauft Apple offiziell?",
        [provider_item(payload), provider_item(payload)])
    assert not exhausted_official_search("Welche iPhones verkauft Apple?",
        [provider_item(payload), provider_item(payload)])


def test_one_rss_only_search_does_not_stop():
    assert not exhausted_official_search("Apple offiziell",
        [provider_item(rss_only_results())])


def test_rss_only_search_does_not_stop_after_a_loaded_article():
    assert not exhausted_official_search("Apple offiziell", [
        provider_item(rss_only_results()), provider_item(rss_only_results()),
        {"action": "fetch_url", "status": "completed",
         "result": {"ok": True, "url": "https://www.apple.com/newsroom/2026/09/article",
                    "text": "Official primary source article. " * 25}},
    ])


def test_mixed_actual_article_link_is_not_dismissed_as_rss_only():
    payload = rss_only_results()
    payload["results"] += [{"url": "https://www.apple.com/newsroom/2026/09/article",
                            "source_type": "article"}]
    payload["count"] = 2
    assert not exhausted_official_search("Apple offiziell",
        [provider_item(payload), provider_item(payload)])


def test_unknown_provider_or_false_degraded_flag_cannot_trigger_rss_stop():
    payload = rss_only_results()
    for change in ({"provider": "unknown"}, {"search_degraded": False},
                   {"count": 2}, {"results": [{"url": "https://evil.example/article",
                       "source_type": "rss_search_entry"}]}):
        candidate = {**payload, **change}
        assert not exhausted_official_search("Apple offiziell",
            [provider_item(candidate), provider_item(candidate)])
