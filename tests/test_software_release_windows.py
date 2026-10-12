"""Release ranking preserves source-exact current-version text and offsets."""
from agent.software_release_windows import python_latest_release_windows
from agent.structured_evidence import build_evidence

GOAL = "Welche Python-3-Version wird auf python.org derzeit als neueste stabile Version veröffentlicht?"


def sample_page():
    return (
        "Download Python\n" + "Generic navigation and menus. " * 35
        + "\nLatest Python 3 Release - Python 3.15.0\n"
        + "This is the latest stable Python release. Download the official files.\n"
        + "Active Python releases\n"
        + "3.15 bugfix Download 2026-10-09\n"
        + "3.14 bugfix Download 2025-10-07\n"
        + "Python releases by version number:\n"
        + "Python 3.15.0 - Oct. 9, 2026 - Download\n"
        + "Python 3.14.8 - Sept. 30, 2026 - Download\n"
        + "Old releases and unrelated navigation. " * 40
    )


def test_python_version_windows_exact_and_current_heading():
    text = sample_page()
    windows = python_latest_release_windows(GOAL, text)
    assert windows
    assert any("Latest Python 3 Release - Python 3.15.0" in excerpt
               for _, _, excerpt in windows)
    assert all(text[start:end] == excerpt for start, end, excerpt in windows)


def test_no_hardcoded_release_and_unrelated_page_ignored():
    text = (
        "Python 3.21.4\n"
        "Latest Python 3 Release - Python 3.21.4\n"
        "This version is declared stable by the page's publisher. " * 4
    )
    win = python_latest_release_windows(GOAL, text)
    assert win and "Python 3.21.4" in win[0][2]
    assert python_latest_release_windows(
        "Welche Go-Version wird empfohlen?", sample_page()
    ) == []


def test_only_release_heading_does_not_invent_newer_version():
    text = "Latest Python 3 Release\nNo release version could be found here."
    assert python_latest_release_windows(GOAL, text) == []


def test_evidence_bundle_prioritizes_exact_release_block():
    text = sample_page()
    bundle = build_evidence([{
        "action": "fetch_url", "status": "completed",
        "query": "https://www.python.org/downloads/",
        "result": {"ok": True, "url": "https://www.python.org/downloads/",
                   "text": text},
    }], goal=GOAL)
    release_facts = [f for f in bundle.facts if "-release-" in f.id]
    assert release_facts
    assert any("Python 3.15.0" in f.evidence_excerpt for f in release_facts)
    assert len([f.id for f in bundle.facts]) == len({f.id for f in bundle.facts})
    for fact in release_facts:
        a, b = fact.source_location
        assert fact.evidence_excerpt == text[a:b]
