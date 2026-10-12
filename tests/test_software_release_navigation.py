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



def test_failed_download_focus_follows_observed_stable_release_link():
    from agent.software_release_navigation import (
        python_source_linked_release_step, needs_python_release_article,
    )

    original = page()
    original["result"]["page_links"] = [
        {"url": "https://www.python.org/downloads/release/python-3148/",
         "title": "Python 3.14.8"},
        {"url": "https://www.python.org/downloads/release/python-3150/",
         "title": "Python 3.15.0"},
        {"url": "https://www.python.org.evil.example/downloads/release/python-9999/",
         "title": "Python 3.99.9"},
        {"url": "https://www.python.org/downloads/release/python-3160a1/",
         "title": "Python 3.16.0a1"},
    ]
    failed = {
        "action": "fetch_url", "status": "completed",
        "query": URL, "instruction": "focus=Active Python releases",
        "result": {"ok": False, "url": URL, "error": "focus_not_found"},
    }
    # A real stable-release hyperlink is stronger navigation than a blind
    # focus attempt, so the article is selected immediately.
    first = python_source_linked_release_step(GOAL, [original])
    assert first["query"] == "https://www.python.org/downloads/release/python-3150/"
    chosen = python_source_linked_release_step(GOAL, [original, failed])
    assert chosen["action"] == "fetch_url"
    assert chosen["query"] == (
        "https://www.python.org/downloads/release/python-3150/"
    )
    assert needs_python_release_article(GOAL, [original, failed])
    completed = {
        "action": "fetch_url", "status": "completed",
        "query": chosen["query"],
        "result": {"ok": True, "url": chosen["query"],
                   "text": "This is an original official publisher article. " * 10},
    }
    assert not needs_python_release_article(GOAL, [original, failed, completed])


def test_python_release_followup_never_guesses_unseen_url():
    from agent.software_release_navigation import python_source_linked_release_step

    original = page()
    original["result"]["page_links"] = [
        {"url": "https://other.example/downloads/release/python-3150/",
         "title": "Python 3.15.0"},
    ]
    failed = {"action": "fetch_url", "status": "completed",
              "query": URL, "instruction": "focus=Active Python releases",
              "result": {"ok": False, "url": URL, "error": "focus_not_found"}}
    assert python_source_linked_release_step(GOAL, [original, failed]) is None



def test_latest_release_fetch_failure_must_not_fall_back_to_older_link():
    from agent.software_release_navigation import python_source_linked_release_step

    original = page()
    latest = "https://www.python.org/downloads/release/python-3150/"
    older = "https://www.python.org/downloads/release/python-3148/"
    original["result"]["page_links"] = [
        {"url": older, "title": "Python 3.14.8"},
        {"url": latest, "title": "Python 3.15.0"},
    ]
    failed_focus = {
        "action": "fetch_url", "status": "completed", "query": URL,
        "instruction": "focus=Active Python releases",
        "result": {"ok": False, "url": URL, "error": "focus_not_found"},
    }
    first = python_source_linked_release_step(GOAL, [original, failed_focus])
    assert first["query"] == latest
    # The newest *observed* release may have become unreachable. This does
    # not make the next older download the "latest" stable Python version.
    failed_article = {
        "action": "fetch_url", "status": "completed", "query": latest,
        "result": {"ok": False, "url": latest, "error": "HTTP 503"},
    }
    assert python_source_linked_release_step(
        GOAL, [original, failed_focus, failed_article],
    ) is None



def test_failed_focus_discovery_uses_only_observed_official_release_index():
    from agent.software_release_navigation import (
        python_release_search_step, needs_python_release_search
    )
    first = page(text="General Python downloads archive. " * 30)
    failed_focus = {
        "action": "fetch_url", "status": "completed",
        "query": URL, "instruction": "focus=Active Python releases",
        "result": {"ok": False, "url": URL, "error": "focus_not_found"},
    }
    assert python_release_search_step(GOAL, [first]) is None
    query = python_release_search_step(GOAL, [first, failed_focus])
    assert query["action"] == "search_web"
    assert "python.org" in query["query"]
    assert needs_python_release_search(GOAL, [first, failed_focus])
    macos = "https://www.python.org/downloads/macos/"
    results = {
        "action": "search_web", "status": "completed",
        "query": query["query"],
        "result": {"results": [
            {"url": "https://www.python.org.evil.example/downloads/macos/",
             "title": "Python releases"},
            {"url": macos, "title": "Python Releases for macOS"},
            {"url": "https://www.python.org/downloads/",
             "title": "Python download front page"},
        ]},
    }
    step = python_release_search_step(GOAL, [first, failed_focus, results])
    assert step["action"] == "fetch_url"
    assert step["query"] == macos
    index = {
        "action": "fetch_url", "status": "completed",
        "query": macos, "result": {
            "ok": True, "url": macos, "text":
                "Latest Python 3 Release - Python 3.15.0. Stable Releases: "
                "Python 3.15.0 - Oct. 9, 2026. " * 6,
        },
    }
    assert not needs_python_release_search(GOAL, [first, failed_focus, results, index])


def test_python_release_search_no_invented_url_no_stale_fallback():
    from agent.software_release_navigation import python_release_search_step
    first = page()
    failed_focus = {
        "action": "fetch_url", "status": "completed",
        "query": URL, "instruction": "focus=Active Python releases",
        "result": {"ok": False, "url": URL, "error": "focus_not_found"},
    }
    query = python_release_search_step(GOAL, [first, failed_focus])
    done_search = {
        "action": "search_web", "status": "completed", "query": query["query"],
        "result": {"results": [{
            "url": "https://untrusted.example/downloads/macos/",
            "title": "Python releases"
        }]},
    }
    assert python_release_search_step(GOAL, [first, failed_focus, done_search]) is None



def test_alternative_official_python_index_replaces_generic_page_in_model_evidence():
    old = page(text="Generic downloads and ancient archived releases. " * 30)
    macos = "https://www.python.org/downloads/macos/"
    official = {
        "action": "fetch_url", "status": "completed",
        "query": macos, "result": {
            "ok": True, "url": macos,
            "text": ("Latest Python 3 Release - Python 3.21.4\n"
                     "Stable Releases\n"
                     "Python 3.21.4 - Oct. 12, 2035\n") * 5,
        },
    }
    originals = [old, official]
    selected = evidence_focus_observations(GOAL, originals)
    assert selected == [official]
    assert originals == [old, official]
    facts = build_evidence(selected, goal=GOAL).facts
    assert facts
    assert any("Python 3.21.4" in f.evidence_excerpt for f in facts)


def test_unrelated_or_spoofed_alternate_index_never_suppresses_original_source():
    old = page()
    bogus = {
        "action": "fetch_url", "status": "completed",
        "query": "https://www.python.org.evil.test/downloads/macos/",
        "result": {
            "ok": True, "url": "https://www.python.org.evil.test/downloads/macos/",
            "text": "Python 3.99.9 " * 10,
        },
    }
    assert evidence_focus_observations(GOAL, [old, bogus]) == [old, bogus]



def test_real_official_release_article_suppresses_redundant_text_focus():
    from agent.software_release_navigation import (
        python_release_focus_step, python_source_linked_release_step,
    )
    original = page()
    url = "https://www.python.org/downloads/release/python-3150/"
    original["result"]["page_links"] = [
        {"url": url, "title": "Python 3.15.0"},
    ]
    next_step = python_source_linked_release_step(GOAL, [original])
    assert next_step["query"] == url
    done = {
        "action": "fetch_url", "status": "completed", "query": url,
        "result": {"ok": True, "url": url, "text":
                   "Python 3.15.0 is the newest stable major release. " * 8},
    }
    assert python_release_focus_step(GOAL, [original, done]) is None
    assert python_source_linked_release_step(GOAL, [original, done]) is None



def test_current_python_release_link_survives_oversized_navigation_menu():
    from agent.page_navigation import same_site_html_links, _MAX_LINKS
    source = (
        "<main>" + "".join(
            f'<a href="/news/old-release/{i}/">Older announcement {i}</a>'
            for i in range(175)
        ) +
        '<a href="/downloads/release/python-3150/">Python 3.15.0</a>' +
        '<a href="https://www.python.org.evil.example/downloads/release/python-9999/">Python 9.99.9</a>' +
        "</main>"
    )
    links = same_site_html_links(source, URL)
    assert len(links) == _MAX_LINKS
    assert any(link["url"] ==
               "https://www.python.org/downloads/release/python-3150/"
               for link in links)
    assert all("evil.example" not in link["url"] for link in links)
