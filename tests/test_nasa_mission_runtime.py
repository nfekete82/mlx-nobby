"""Agent-level NASA mission navigation from discovered publisher links."""
from dataclasses import replace

from test_agent_runtime import AgentRuntimeTests

GOAL = (
    "Wann landete Apollo 11 nach Angaben der NASA auf dem Mond, "
    "und wer betrat die Oberfläche zuerst?"
)
HOME = "https://www.nasa.gov/"
INDEX = "https://www.nasa.gov/a-to-z-of-nasa-missions/"
ARTICLE = "https://www.nasa.gov/mission/apollo-11/"


def test_agent_reads_source_discovered_nasa_mission_without_planner():
    harness = AgentRuntimeTests()
    harness.setUp()
    calls = []

    def do_search(**kwargs):
        calls.append(("search", kwargs["query"]))
        # SearXNG's current Bing results can be irrelevant; real-site
        # navigation must recover without fabricating an article path.
        domain = "https://www.apollo.de/" if sum(
            1 for name, _ in calls if name == "search"
        ) == 1 else "https://www.apollo.io/"
        return {"provider": "SearXNG", "results": [{
            "url": domain, "title": "Unrelated Apollo business",
        }]}

    def do_fetch(**kwargs):
        url = kwargs["query"]
        calls.append(("fetch", url))
        assert url in {HOME, INDEX, ARTICLE}
        links = {
            HOME: [{"url": INDEX, "title": "A to Z List of Missions"}],
            INDEX: [
                {"url": "https://www.nasa.gov/mission/apollo-17/",
                 "title": "Apollo 17"},
                {"url": ARTICLE, "title": "Apollo 11"},
            ],
            ARTICLE: [],
        }[url]
        text = (
            "NASA official agency overview. " * 20 if url == HOME else
            "A to Z list of NASA missions and launches. " * 20 if url == INDEX else
            "NASA Apollo 11 mission: lunar landing on July 20, 1969. "
            "Neil Armstrong was the first human on the lunar surface. "
            "The astronauts then completed their exploration. " * 8
        )
        return {"ok": True, "url": url, "page_links": links, "text": text}

    def evidence_answer(goal, observations):
        loaded = [
            step.get("query")
            for step in observations
            if step.get("action") == "fetch_url"
        ]
        assert loaded == [HOME, INDEX, ARTICLE]
        return "Sources fetched; individual claims still require verification"

    harness.add_tool("search_web", do_search)
    harness.add_tool("fetch_url", do_fetch)
    harness.hooks = replace(
        harness.hooks, agent_evidence_answer=evidence_answer,
    )
    result = harness.runtime([]).run(GOAL, mode="diagnostic")
    assert result["status"] == "completed"
    assert [step["action"] for step in result["steps"]] == [
        "search_web", "search_web", "fetch_url",
        "fetch_url", "fetch_url",
    ]
    assert not harness.provider.calls
