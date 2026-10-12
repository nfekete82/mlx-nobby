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



def test_seasonal_influenza_rejects_zoonotic_result_and_link():
    wrong = (
        "https://www.rki.de/DE/Themen/Infektionskrankheiten/"
        "Infektionskrankheiten-A-Z/Z/ZoonotischeInfluenza/Vogelgrippe.html"
    )
    seasonal = "https://www.rki.de/SharedDocs/FAQs/DE/Influenza/FAQ_Liste.html"
    observations = [{
        "action": "search_web", "status": "completed",
        "query": "rki influenza",
        "result": {"results": [
            {"url": wrong, "title": "Zoonotische Influenza / Vogelgrippe"},
            {"url": seasonal, "title": "Krankheitsbild der Influenza FAQ"},
        ]},
    }]
    chosen = choose_official_publisher_step(GOAL, observations)
    assert chosen["action"] == "fetch_url"
    assert chosen["query"] == seasonal

    observations = [home()]
    observations[0]["result"]["page_links"] = [{
        "url": wrong, "title": "Influenza zoonotisch",
    }]
    chosen = choose_official_publisher_step(GOAL, observations)
    assert not (chosen and chosen.get("query") == wrong)


def test_explicit_zoonotic_question_allows_its_source_urls():
    from agent.official_source_navigation import _irrelevant_clinical_variant
    url = "https://www.rki.de/DE/Themen/ZoonotischeInfluenza/Vogelgrippe.html"
    assert _irrelevant_clinical_variant(GOAL, url)
    assert not _irrelevant_clinical_variant(
        "Welche typischen Symptome einer zoonotischen Influenza nennt das RKI?", url,
    )
