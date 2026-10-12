"""Source-observed government explanation closes statutory five-day leave gap."""
from agent.leave_source_navigation import (
    _five_day_leave_question, choose_leave_explanation_step,
    needs_leave_explanation,
)

GOAL = (
    "Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer in "
    "Deutschland bei einer Fünf-Tage-Woche? Bitte nenne die Rechtsgrundlage."
)
LAW = "https://www.gesetze-im-internet.de/burlg/BJNR000020963.html"
BMAS = (
    "https://www.bmas.de/DE/Arbeit/Arbeitsrecht/"
    "Teilzeit-flexible-Arbeitszeit/Teilzeit/"
    "Fragen-und-Antworten-Brueckenteilzeit/faq-brueckenteilzeit.html"
)


def fetched(url, text="Bundesurlaubsgesetz: 24 Werktage minimum. " * 5):
    return {"action": "fetch_url", "status": "completed", "query": url,
            "result": {"ok": True, "url": url, "text": text}}


def searched(query, *hits):
    return {"action": "search_web", "status": "completed", "query": query,
            "result": {"provider": "SearXNG", "results": list(hits)}}


def test_statute_requires_credible_official_workweek_explanation():
    assert _five_day_leave_question(GOAL)
    assert choose_leave_explanation_step(GOAL, []) is None
    observations = [fetched(LAW)]
    first = choose_leave_explanation_step(GOAL, observations)
    assert first["action"] == "search_web"
    assert "bmas.de" in first["query"]
    assert "20 Arbeitstage" not in first["query"]
    assert needs_leave_explanation(GOAL, observations)

    observations.append(searched(first["query"],
        {"url": "https://www.bmas.de/DE/Service/Gesetze-und-Gesetzesvorhaben/bundesurlaubsgesetz.html",
         "title": "Bundesurlaubsgesetz - BMAS"},
        {"url": BMAS, "title": "Fragen und Antworten zur Brückenteilzeit"},
    ))
    second = choose_leave_explanation_step(GOAL, observations)
    assert second["action"] == "fetch_url"
    assert second["query"] == BMAS

    original = list(observations)
    observations.append(fetched(BMAS, "Der gesetzliche Mindesturlaub beträgt "
       "bei einer 5-Tage-Woche 20 Arbeitstage. " * 5))
    assert choose_leave_explanation_step(GOAL, observations) is None
    assert observations[:len(original)] == original


def test_irrelevant_bmas_statute_only_does_not_prove_five_day_total():
    obs = [fetched(LAW)]
    q = choose_leave_explanation_step(GOAL, obs)["query"]
    generic = "https://www.bmas.de/DE/Service/Gesetze-und-Gesetzesvorhaben/bundesurlaubsgesetz.html"
    obs += [searched(q, {"url": generic, "title": "Bundesurlaubsgesetz - BMAS"})]
    selected = choose_leave_explanation_step(GOAL, obs)
    assert selected["query"] == generic
    obs.append(fetched(generic, "Das Bundesurlaubsgesetz gewährt bezahlten Urlaub. " * 10))
    assert choose_leave_explanation_step(GOAL, obs) is None  # No more links from that query


def test_fails_closed_for_spoof_and_unrelated_questions():
    q = choose_leave_explanation_step(GOAL, [fetched(LAW)])["query"]
    fake = "https://www.bmas.de.evil.example/help/urlaub"
    obs = [fetched(LAW), searched(q, {"url": fake, "title": "Urlaub"})]
    assert choose_leave_explanation_step(GOAL, obs) is None
    assert choose_leave_explanation_step("Was sagt das BUrlG?", obs) is None
