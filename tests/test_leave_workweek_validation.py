"""A five-day minimum-leave question must not certify six-day Werktage."""
from agent.leave_workweek_validation import incompatible_leave_workweek
from agent.semantic_evidence import SemanticClaim, _final_validation
from agent.structured_evidence import build_evidence

LAW = (
    "§ 3 Dauer des Urlaubs. Der Urlaub beträgt jährlich mindestens 24 Werktage. "
    "Als Werktage gelten alle Kalendertage, die nicht Sonn- oder gesetzliche "
    "Feiertage sind."
)
GOAL = (
    "Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer in Deutschland "
    "bei einer Fünf-Tage-Woche? Bitte nenne die Rechtsgrundlage."
)
BAD = (
    "Arbeitnehmer in Deutschland haben bei einer Fünf-Tage-Woche "
    "einen gesetzlichen Mindesturlaub von 24 Werktagen pro Jahr."
)


def test_statutory_werktage_do_not_count_as_five_day_arbeitstage():
    assert incompatible_leave_workweek(GOAL, BAD, [LAW])
    assert incompatible_leave_workweek(
        GOAL, "Der gesetzliche Mindesturlaub beträgt 24 Urlaubstage.", [LAW]
    )
    assert not incompatible_leave_workweek(
        GOAL, "Der gesetzliche Mindesturlaub beträgt 20 Arbeitstage.", [LAW]
    )
    assert not incompatible_leave_workweek(
        "Wie viele Werktage sind im Gesetz für eine Sechs-Tage-Woche genannt?",
        "Der Mindesturlaub beträgt 24 Werktage.", [LAW],
    )
    assert not incompatible_leave_workweek(GOAL, BAD, [
        "Ein journalistischer Kommentar, der eine Zahl nennt, ist kein Gesetzesbeleg."
    ])
    assert not incompatible_leave_workweek(GOAL, BAD, [])


def test_semantic_supported_downgraded_without_inventing_correct_total():
    url = "https://www.gesetze-im-internet.de/burlg/__3.html"
    observations = [{
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": True, "url": url, "text": LAW},
    }]
    bundle = build_evidence(observations, goal=GOAL)
    passage = next(f for f in bundle.facts if "24 Werktage" in f.evidence_excerpt)
    claim = SemanticClaim(
        "c-1", "Mindesturlaub", "gesetzliche_mindesturlaubstage", "24 Werktage",
        (), BAD, (passage.id,)
    )
    decisions = [{
        "id": "c-1", "status": "supported", "reason": "Source says 24 Werktage",
        "passage_ids": [passage.id],
        "decision_origin": "model",
    }]
    checked = _final_validation(
        [claim], decisions, observations, goal=GOAL, bundle=bundle
    )
    assert checked[0]["status"] == "insufficient_evidence"
    assert checked[0]["decision_origin"] == "leave_unit_validation"
    assert checked[0]["passage_ids"] == [passage.id]
    assert decisions[0]["status"] == "supported"


def test_unrelated_subjects_and_valid_five_day_statements_not_vetoed():
    goal = "Wie viele gesetzliche Mindesturlaubstage gibt es bei einer Fünf-Tage-Woche?"
    assert not incompatible_leave_workweek(
        goal, "Die Grundlage nennt 20 Arbeitstage.", [LAW]
    )
    assert not incompatible_leave_workweek(
        "Wie viele Tage dauert das Seminar bei einer Fünf-Tage-Woche?",
        "Das Seminar dauert 24 Tage.", [LAW]
    )
