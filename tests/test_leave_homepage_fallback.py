"""An observed publisher homepage may be used for bounded navigation."""
from agent.leave_source_navigation import choose_leave_official_discovery_step

GOAL = ("Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer in "
        "Deutschland bei einer Fünf-Tage-Woche?")
SEARCHES = [
    "gesetze-im-internet.de Bundesurlaubsgesetz § 3 Mindesturlaub",
    "bmas.de Mindesturlaub Fünf-Tage-Woche Urlaubsanspruch",
]


def search(url):
    return {
        "action": "search_web", "status": "completed",
        "query": SEARCHES[0],
        "result": {"results": [{"url": url, "title": "Gesetze im Internet"}]},
    }


def test_official_homepage_is_selected_only_after_bounded_queries():
    first = search("https://www.gesetze-im-internet.de/")
    second = {
        "action": "search_web", "status": "completed",
        "query": SEARCHES[1], "result": {"results": []}
    }
    initial = choose_leave_official_discovery_step(GOAL, [first])
    assert initial["action"] == "search_web"
    decision = choose_leave_official_discovery_step(GOAL, [first, second])
    assert decision["action"] == "fetch_url"
    assert decision["query"] == "https://www.gesetze-im-internet.de/"


def test_spoof_and_non_https_homepages_are_not_selected():
    for url in (
        "http://www.gesetze-im-internet.de/",
        "https://www.gesetze-im-internet.de.evil.example/",
        "https://www.gesetze-im-internet.de/?redirect=evil",
    ):
        steps = [search(url), {
            "action": "search_web", "status": "completed",
            "query": SEARCHES[1], "result": {"results": []},
        }]
        assert choose_leave_official_discovery_step(GOAL, steps) is None


def test_homepage_is_never_reopened_after_attempt():
    first = search("https://www.gesetze-im-internet.de/")
    second = {
        "action": "search_web", "status": "completed",
        "query": SEARCHES[1], "result": {"results": []}
    }
    failed = {
        "action": "fetch_url", "status": "completed",
        "query": "https://www.gesetze-im-internet.de/",
        "result": {"ok": False, "url": "https://www.gesetze-im-internet.de/"},
    }
    assert choose_leave_official_discovery_step(
        GOAL, [first, second, failed]
    ) is None
