"""Release metadata and client cache contract for MLX-Nobby 1.14.0."""
from pathlib import Path
import re


def test_version_matches_release_heading_and_library_cache():
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## v{version}" in changelog
    html = (root / "frontend/chat.html").read_text(encoding="utf-8")
    assert f'media-library.js?v={version.replace(".", "-")}-studio' in html
    assert f'media-library.css?v={version.replace(".", "-")}-studio' in html
    assert 'media-library.js?v=1-13-' not in html
