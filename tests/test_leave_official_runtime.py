"""Real runtime traverses official leave sources without model plan detours."""
from dataclasses import replace
from test_agent_runtime import AgentRuntimeTests

GOAL = (
    "Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer in "
    "Deutschland bei einer Fünf-Tage-Woche? Bitte nenne die Rechtsgrundlage."
)
LAW = "https://www.gesetze-im-internet.de/burlg/BJNR000020963.html"
FAQ = ("https://www.bmas.de/DE/Arbeit/Arbeitsrecht/Teilzeit-flexible-Arbeitszeit/"
       "Teilzeit/Fragen-und-Antworten-Brueckenteilzeit/faq-brueckenteilzeit.html")


def test_research_runtime_reaches_both_government_pages_before_verifier():
    h = AgentRuntimeTests()
    h.setUp()
    observed_searches = []

    def search(**kwargs):
        query = kwargs["query"]
        observed_searches.append(query)
        if "gesetze-im-internet.de" in query:
            return {"provider": "SearXNG", "results": [
                {"url": LAW, "title": "Bundesurlaubsgesetz § 3"}
            ]}
        if "bmas.de" in query:
            return {"provider": "SearXNG", "results": [
                {"url": FAQ, "title": "Brückenteilzeit: Urlaubsanspruch"}
            ]}
        raise AssertionError(f"unexpected model search {query}")

    def fetch(**kwargs):
        url = kwargs["query"]
        if url == LAW:
            return {"ok": True, "url": LAW,
                    "text": ("§ 3 BUrlG: Der Urlaub beträgt jährlich "
                             "mindestens 24 Werktage. " * 10)}
        if url == FAQ:
            return {"ok": True, "url": FAQ,
                    "text": ("Das Bundesurlaubsgesetz gewährt vier Wochen; "
                             "bei einer 5-Tage-Woche sind dies 20 Arbeitstage. " * 10)}
        raise AssertionError(f"unexpected URL {url}")

    def evidence_answer(goal, observations):
        loaded = [step["result"]["url"] for step in observations
                  if step.get("action") == "fetch_url"
                  and step.get("result", {}).get("ok") is True]
        assert loaded == [LAW, FAQ]
        return "Both official sources fetched; independent verifier still required"

    h.add_tool("search_web", search)
    h.add_tool("fetch_url", fetch)
    h.hooks = replace(h.hooks, agent_evidence_answer=evidence_answer)
    result = h.runtime([]).run(GOAL, mode="diagnostic")
    assert result["status"] == "completed"
    assert [step["action"] for step in result["steps"]] == [
        "search_web", "fetch_url", "search_web", "fetch_url",
    ]
    assert len(observed_searches) == 2
    assert not h.provider.calls
