from agent.leave_workweek_validation import grounded_five_day_leave

GOAL = (
    "Wie viele gesetzliche Mindesturlaubstage haben Arbeitnehmer "
    "in Deutschland bei einer Fünf-Tage-Woche?"
)
URL = "https://www.gesetze-im-internet.de/burlg/__3.html"
TEXT = (
    "§ 3 Dauer des Urlaubs\n"
    "(1) Der Urlaub beträgt jährlich mindestens 24 Werktage. "
    "(2) Als Werktage gelten alle Kalendertage, "
    "die nicht Sonn- oder gesetzliche Feiertage sind."
)


def observation(url=URL, text=TEXT):
    return {
        "action": "fetch_url",
        "status": "completed",
        "result": {"ok": True, "url": url, "text": text}
    }


def test_official_source_derives_20_days():
    result = grounded_five_day_leave(GOAL, [observation()])
    assert result is not None
    assert result["result_workdays"] == 20
    assert result["source_werktage"] == 24


def test_spoofed_domain_rejected():
    url = "https://www.gesetze-im-internet.de.evil.test/burlg/__3.html"
    assert grounded_five_day_leave(
        GOAL, [observation(url=url)]
    ) is None


def test_missing_legal_definition_rejected():
    assert grounded_five_day_leave(
        GOAL, [observation(text="Der Urlaub beträgt jährlich mindestens 24 Werktage.")]
    ) is None


def test_unrelated_question_not_derived():
    assert grounded_five_day_leave(
        "Wie viele Urlaubstage bei einer Sechs-Tage-Woche?",
        [observation()]
    ) is None
