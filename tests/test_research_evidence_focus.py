"""Navigation-only sources are removed only after a real primary article loads."""
from agent.research_evidence_focus import evidence_focus_observations
from agent.structured_evidence import build_evidence

GOAL = (
    "Wann landete Apollo 11 nach Angaben der NASA auf dem Mond, "
    "und wer betrat die Oberfläche zuerst?"
)
HOME = "https://www.nasa.gov/"
INDEX = "https://www.nasa.gov/a-to-z-of-nasa-missions/"
ARTICLE = "https://www.nasa.gov/mission/apollo-11/"


def fetched(url, content, ok=True):
    return {
        "action": "fetch_url", "status": "completed",
        "query": url, "result": {
            "ok": ok, "url": url, "text": content,
        },
    }


def test_original_trace_kept_but_model_context_uses_article():
    navigation = "Generic navigation to NASA missions. " * 15
    article = (
        "Apollo 11 Moon landing on July 20, 1969. "
        "Neil Armstrong was the first person to step on the lunar surface. "
    ) * 6
    observations = [
        fetched(HOME, navigation),
        fetched(INDEX, navigation),
        fetched(ARTICLE, article),
    ]
    focused = evidence_focus_observations(GOAL, observations)
    assert [s["query"] for s in focused] == [ARTICLE]
    assert [s["query"] for s in observations] == [HOME, INDEX, ARTICLE]
    bundle = build_evidence(focused, goal=GOAL)
    assert len(bundle.sources) == 1
    assert bundle.sources[0].final_url == ARTICLE
    assert any("July 20, 1969" in fact.evidence_excerpt for fact in bundle.facts)


def test_failed_spoofed_or_other_mission_document_never_triggers_filter():
    navigation = "NASA mission page. " * 20
    home, index = fetched(HOME, navigation), fetched(INDEX, navigation)
    for url, ok in (
        (ARTICLE, False),
        ("https://www.nasa.gov.evil.example/mission/apollo-11/", True),
        ("https://www.nasa.gov/mission/apollo-17/", True),
    ):
        steps = [home, index, fetched(url, navigation, ok)]
        assert evidence_focus_observations(GOAL, steps) is steps


def test_other_publishers_and_nonmission_questions_are_untouched():
    steps = [fetched(HOME, "NASA site. " * 20),
             fetched(ARTICLE, "NASA mission. " * 20)]
    assert evidence_focus_observations(
        "Was ist NASA?", steps,
    ) is steps
    assert evidence_focus_observations(
        "Wann fiel die Berliner Mauer laut bpb.de?", steps,
    ) is steps


def test_other_nasa_articles_are_not_dropped_with_discovery_pages():
    article = "NASA mission Apollo 11 landing story. " * 15
    companion = "NASA supporting chronology and source. " * 15
    steps = [
        fetched(HOME, "Navigation. " * 30),
        fetched(INDEX, "Mission directory. " * 20),
        fetched(ARTICLE, article),
        fetched("https://www.nasa.gov/history/apollo-11-chronology/", companion),
    ]
    chosen = evidence_focus_observations(GOAL, steps)
    assert [s["query"] for s in chosen] == [
        ARTICLE, "https://www.nasa.gov/history/apollo-11-chronology/",
    ]
