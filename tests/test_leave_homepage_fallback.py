"""A publisher homepage is not evidence of a statute and must not preempt research."""
from agent.leave_source_navigation import choose_leave_official_discovery_step

GOAL = ("Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer "
        "in Deutschland bei einer Fünf-Tage-Woche?")
SEARCHES = (
    "gesetze-im-internet.de Bundesurlaubsgesetz § 3 Mindesturlaub",
    "bmas.de Mindesturlaub Fünf-Tage-Woche Urlaubsanspruch",
)


def searches(url):
    return [
        {"action": "search_web", "status": "completed", "query": query,
         "result": {"results": [{"url": url, "title": "Gesetze im Internet"}]}}
        for query in SEARCHES
    ]


def test_homepage_only_results_do_not_count_as_law_evidence():
    steps = searches("https://www.gesetze-im-internet.de/")
    assert choose_leave_official_discovery_step(GOAL, steps) is None


def test_spoofed_homepages_not_selected():
    for url in (
        "http://www.gesetze-im-internet.de/",
        "https://www.gesetze-im-internet.de.evil.example/",
        "https://www.gesetze-im-internet.de/?redirect=evil",
    ):
        assert choose_leave_official_discovery_step(
            GOAL, searches(url)
        ) is None


def test_unrelated_question_cannot_trigger_leave_navigation():
    assert choose_leave_official_discovery_step(
        "Was ist die neueste stabile Python-Version?",
        searches("https://www.gesetze-im-internet.de/"),
    ) is None
