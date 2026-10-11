"""The official search fastpath only stops proven empty retrieval."""
from agent.search_failure_fastpath import exhausted_official_search


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
