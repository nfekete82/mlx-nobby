"""Product release metadata and independently versioned media-library assets."""
from pathlib import Path
import re


def test_version_matches_release_heading_and_library_cache():
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## v{version}" in changelog

    html = (root / "frontend/chat.html").read_text(encoding="utf-8")
    # Asset cache revisions change when their assets change, not whenever the
    # product VERSION changes. A release must not force a cache-version bump.
    assert re.search(r'media-library\.js\?v=[A-Za-z0-9][A-Za-z0-9._-]*', html)
    assert "media-library.css?v=1-18-shared-pickers" in html
    assert 'media-library.js?v=1-13-' not in html
