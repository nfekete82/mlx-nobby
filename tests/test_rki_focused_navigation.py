"""RKI clinical research gets a distinct, source-scoped retry only once."""
from agent.official_source_navigation import choose_official_publisher_step

GOAL = "Welche typischen Symptome einer Influenza nennt das Robert Koch-Institut?"
HOME = "https://www.rki.de/DE/Home/home_node.html"


def home():
    return {
        "action": "fetch_url", "status": "completed", "query": HOME,
        "result": {
            "ok": True, "url": HOME,
            "text": "Das Robert Koch-Institut ist die zentrale deutsche Institution "
                    "für Infektionskrankheiten. " * 6,
            "page_links": [],
        },
    }


def test_one_new_focused_rki_search_after_generic_homepage():
    observations = [home()]
    next_step = choose_official_publisher_step(GOAL, observations)
    assert next_step["action"] == "search_web"
    assert "Krankheitsbild der influenza" in next_step["query"]
    assert next_step["query"].startswith("!go ")
    assert "FAQ_Liste.html" not in next_step["query"]
    # The resulting search still must yield a discovered, fetched article.
    observations.append({
        "action": "search_web", "status": "completed",
        "query": next_step["query"],
        "result": {"results": [], "provider": "SearXNG"},
    })
    another = choose_official_publisher_step(GOAL, observations)
    assert another is None or another.get("query") != next_step["query"]


def test_no_medical_symptoms_are_embedded_as_search_facts():
    next_step = choose_official_publisher_step(GOAL, [home()])
    assert "fieber" not in next_step["query"].casefold()
    assert "husten" not in next_step["query"].casefold()
