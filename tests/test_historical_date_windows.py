"""Historical date extraction retains source-exact day/month/year spans.

No source date is treated as an established event date without the verifier.
"""
from agent.structured_evidence import _temporal_windows, build_evidence

GOAL = (
    "Wann landete Apollo 11 nach Angaben der NASA auf dem Mond, "
    "und wer betrat die Oberfläche zuerst?"
)
URL = "https://www.nasa.gov/mission/apollo-11/"


def nasa_source():
    # Use authentic NASA date formats without pretending the fixtures are
    # independent proof of any historical claim.
    return (
        "Apollo 11 \n" + "General mission description. " * 23 + "\n"
        "Launch\nJuly 16, 1969\n" + "Launch vehicle preparation. " * 25 + "\n"
        "SPLASHDOWN\nJuly 24, 1969\n" + "Return to Earth coverage. " * 22 + "\n"
        "Apollo 11 Mission Overview\n"
        "July 20, 1969: One Giant Leap For Mankind\n"
        "The lunar module made its landing on the Moon. "
        "Neil Armstrong took the first steps on the Moon.\n"
    )


def test_when_question_keeps_exact_us_date_and_landing_context():
    text = nasa_source()
    assert _temporal_windows("Was ist das Apollo-Programm?", text) == []
    windows = _temporal_windows(GOAL, text)
    assert windows
    assert any("July 20, 1969" in excerpt for _, _, excerpt in windows)
    assert windows[0][2].find("July 20, 1969") >= 0
    assert all(text[a:b] == excerpt for a, b, excerpt in windows)


def test_common_date_formats_do_not_invent_a_date():
    question = "Wann fand das Ereignis laut dieser Quelle statt?"
    for written in ("July 20, 1969", "20 July 1969",
                    "20. Juli 1969", "1969-07-20"):
        text = f"Historical event occurred on {written}, according to the source."
        windows = _temporal_windows(question, text)
        assert any(written in excerpt for _, _, excerpt in windows)
        assert all(text[a:b] == excerpt for a, b, excerpt in windows)
    assert _temporal_windows(question, "The event happened sometime in July 1969.") == []


def test_evidence_passage_retains_exact_day_and_original_offsets():
    text = nasa_source()
    observations = [{
        "action": "fetch_url", "status": "completed", "query": URL,
        "result": {"ok": True, "url": URL, "text": text},
    }]
    bundle = build_evidence(observations, goal=GOAL)
    dates = [fact for fact in bundle.facts if "-date-" in fact.id]
    assert any("July 20, 1969" in f.evidence_excerpt for f in dates)
    for fact in dates:
        a, b = fact.source_location
        assert text[a:b] == fact.evidence_excerpt


def test_finance_temporal_window_keeps_effective_date_context():
    question = "Seit welchem Datum gilt der Einlagezins der EZB?"
    text = (
        "ECB KEY INTEREST RATES\n"
        "Deposit facility | 2.00 % | 1 January 2026\n"
        "The following rate table lists effective dates.\n"
    )
    dates = _temporal_windows(question, text)
    assert any("1 January 2026" in p[2] and "2.00 %" in p[2] for p in dates)
