"""NASA date follow-up is grounded in actual mission-profile hyperlinks."""
from dataclasses import replace

from agent.official_source_navigation import (
    choose_official_publisher_step, has_discovered_deeper_primary_link,
    _nasa_landing_chronology_step,
)
from agent.page_navigation import same_site_html_links, _MAX_LINKS

GOAL = (
    "Wann landete Apollo 11 nach Angaben der NASA auf dem Mond, "
    "und wer betrat die Oberfläche zuerst?"
)
HOME = "https://www.nasa.gov/"
INDEX = "https://www.nasa.gov/a-to-z-of-nasa-missions/"
MISSION = "https://www.nasa.gov/mission/apollo-11/"
CHRONOLOGY = "https://www.nasa.gov/missions/apollo/apollo-11/apollo-11-mission-overview/"


def fetched(url, links=()):
    return {"action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "page_links": list(links),
                       "text": ("NASA official historical mission page. " * 10)}}


def test_late_actual_chronology_link_survives_96_link_cap():
    html = (
        "<main>" + "".join(
            f'<a href="/news-release/other/{i}/story/">News {i}</a>'
            for i in range(175)
        )
        + '<a href="/missions/apollo/apollo-11/apollo-11-mission-overview/">Read the Story</a>'
        + '<a href="https://www.nasa.gov.evil.example/missions/apollo/apollo-11/apollo-11-mission-overview/">Spoof</a>'
        + "</main>"
    )
    links = same_site_html_links(html, MISSION)
    assert len(links) == _MAX_LINKS
    assert any(link["url"] == CHRONOLOGY for link in links)
    assert all("evil.example" not in link["url"] for link in links)


def test_followup_chooses_only_source_discovered_matching_chronology():
    observations = [
        fetched(HOME), fetched(INDEX),
        fetched(MISSION, [
            {"url": "https://www.nasa.gov/missions/apollo/apollo-17/apollo-17-mission-overview/",
             "title": "Wrong mission"},
            {"url": "https://www.nasa.gov.evil.example/missions/apollo/apollo-11/apollo-11-mission-overview/",
             "title": "Spoof"},
            {"url": CHRONOLOGY, "title": "Read the Story"},
        ]),
    ]
    decision = choose_official_publisher_step(GOAL, observations)
    assert decision["action"] == "fetch_url"
    assert decision["query"] == CHRONOLOGY
    assert has_discovered_deeper_primary_link(GOAL, observations)

    observations.append(fetched(CHRONOLOGY))
    assert _nasa_landing_chronology_step(GOAL, observations) is None
    assert not has_discovered_deeper_primary_link(GOAL, observations)


def test_no_source_link_does_not_invent_chronology():
    observations = [fetched(HOME), fetched(INDEX), fetched(MISSION)]
    assert _nasa_landing_chronology_step(GOAL, observations) is None
    assert not has_discovered_deeper_primary_link(GOAL, observations)
    other = "Wer war die erste Person auf dem Mond laut NASA Apollo 11?"
    observations[2]["result"]["page_links"] = [
        {"url": CHRONOLOGY, "title": "Read the Story"}
    ]
    assert _nasa_landing_chronology_step(other, observations) is None


def test_agent_runtime_follows_chronology_before_evidence_verification():
    from test_agent_runtime import AgentRuntimeTests

    harness = AgentRuntimeTests()
    harness.setUp()
    calls = []

    def do_search(**kwargs):
        calls.append(("search", kwargs["query"]))
        return {"provider": "SearXNG", "results": [{
            "url": "https://www.apollo.de/",
            "title": "Optics not space history",
        }]}

    def do_fetch(**kwargs):
        url = kwargs["query"]
        calls.append(("fetch", url))
        assert url in {HOME, INDEX, MISSION, CHRONOLOGY}
        pages = {
            HOME: [{"url": INDEX, "title": "A to Z List of Missions"}],
            INDEX: [{"url": MISSION, "title": "Apollo 11"}],
            MISSION: [{"url": CHRONOLOGY, "title": "Read the Story"}],
            CHRONOLOGY: [],
        }
        text = (
            "NASA Apollo 11 Moon mission news. " * 20 if url != CHRONOLOGY else
            "NASA Apollo 11: On July 20, 1969, the Lunar Module "
            "descended to the Moon and touched down in the Sea of Tranquility. "
            "Neil Armstrong was the first human to step onto the surface. " * 5
        )
        return {"ok": True, "url": url, "text": text,
                "page_links": pages[url]}

    def evidence_answer(goal, observations):
        assert [s["query"] for s in observations
                if s.get("action") == "fetch_url"] == [
                    HOME, INDEX, MISSION, CHRONOLOGY,
                ]
        return "Chronology loaded; model claim verifier still required"

    harness.add_tool("search_web", do_search)
    harness.add_tool("fetch_url", do_fetch)
    harness.hooks = replace(harness.hooks, agent_evidence_answer=evidence_answer)
    result = harness.runtime([]).run(GOAL, mode="diagnostic")
    assert result["status"] == "completed"
    assert [s["action"] for s in result["steps"]] == [
        "search_web", "search_web", "fetch_url", "fetch_url",
        "fetch_url", "fetch_url",
    ]
    assert not harness.provider.calls
