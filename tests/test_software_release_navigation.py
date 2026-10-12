"""Read real Python's published release block before asking a model to infer a version."""
from agent.software_release_navigation import (
    python_latest_version_question, python_release_focus_step,
    needs_python_release_focus,
)
from agent.research_evidence_focus import evidence_focus_observations
from agent.structured_evidence import build_evidence

GOAL = "Welche Python-3-Version wird auf python.org derzeit als neueste stabile Version veröffentlicht?"
URL = "https://www.python.org/downloads/"


def page(*, focus=None, text=None):
    if text is None:
        text = "Active Python releases\n3.15 bugfix Download 2026-10-09\n" + (
            "Generic Python download navigation. " * 15
        )
    return {"action": "fetch_url", "status": "completed",
            "query": URL,
            "instruction": ("focus=Active Python releases" if focus else None),
            "result": {"ok": True, "url": URL, "text": text, "focus": focus,
                       "offset": 2000 if focus else 0}}


def test_focus_is_official_previously_fetched_url_only():
    assert python_latest_version_question(GOAL)
    assert python_release_focus_step(GOAL, []) is None
    original = page()
    result = python_release_focus_step(GOAL, [original])
    assert result["action"] == "fetch_url"
    assert result["query"] == URL
    assert result["instruction"] == "focus=Active Python releases"
    assert needs_python_release_focus(GOAL, [original])
    assert not needs_python_release_focus(GOAL, [original, page(focus="Active Python releases")])


def test_absent_or_failed_retrieval_never_invents_url_or_version():
    assert not python_latest_version_question("Wer erfand Python?")
    fail = {"action": "fetch_url", "status": "completed",
            "query": URL, "result": {"ok": False, "url": URL}}
    assert python_release_focus_step(GOAL, [fail]) is None
    spoof = page()
    spoof["result"]["url"] = "https://python.org.evil.example/downloads/"
    assert python_release_focus_step(GOAL, [spoof]) is None
    attempted = page()
    attempted["instruction"] = "focus=Active Python releases"
    assert python_release_focus_step(GOAL, [page(), attempted]) is None


def test_focused_original_passage_used_without_mutating_trace():
    generic = page(text="Navigation, unrelated version names and old archives. " * 130)
    source = (
        "Active Python releases\n"
        "Python version Maintenance status First released\n"
        "3.15 bugfix Download 2026-10-09\n"
        "3.14 bugfix Download 2025-10-07\n"
        "Python releases by version number:\n"
        "Python 3.15.0 Oct. 9, 2026 Download\n"
        "Python 3.14.8 Sept. 30, 2026 Download\n"
        + "More current publisher release details. " * 12
    )
    focus = page(focus="Active Python releases", text=source)
    observations = [generic, focus]
    reduced = evidence_focus_observations(GOAL, observations)
    assert reduced == [focus]
    assert observations == [generic, focus]
    facts = build_evidence(reduced, goal=GOAL).facts
    assert any("Python 3.15.0" in f.evidence_excerpt for f in facts)
    for fact in facts:
        a, b = fact.source_location
        assert focus["result"]["offset"] <= a < b
        assert source[a - focus["result"]["offset"]:b - focus["result"]["offset"]] == fact.evidence_excerpt


def test_non_release_questions_leave_sources_untouched():
    observations = [page(), page(focus="Active Python releases")]
    assert evidence_focus_observations("Was ist Python?", observations) is observations



def test_focused_fetch_falls_back_to_real_version_heading_not_a_guess():
    from agent.app import source_focus_offset

    text = (
        "Python downloads and installable releases. " * 40
        + "\nLatest Python 3 Release - Python 3.21.4\n"
        + "This is a publisher-verified stable version of the language. " * 5
    )
    offset = source_focus_offset(text, "Active Python releases")
    assert offset is not None
    assert "Latest Python 3 Release - Python 3.21.4" in text[offset:offset+6000]

    text2 = (
        "Python downloads intro. " * 60
        + "\nPython releases by version number:\n"
        + "Python 3.99.3 - Oct. 12, 2035 - Download\n"
        + "Previous older versions follow. " * 20
    )
    offset = source_focus_offset(text2, "Active Python releases")
    assert offset is not None
    assert "Python 3.99.3" in text2[offset:offset+6000]


def test_focused_fetch_refuses_to_fabricate_release_section():
    from agent.app import source_focus_offset

    assert source_focus_offset(
        "Navigation and policies, no versions or release headings. " * 40,
        "Active Python releases",
    ) is None
    assert source_focus_offset("An unrelated clinical page. " * 30,
                               "Some other absent heading") is None
